"""Decide a category and a descriptive name for one file."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import Config
from .db import DB
from .extract import RULE_CATEGORY, Content, extract
from .llm import LLM, LLMError

_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
             *(f"LPT{i}" for i in range(1, 10))}


@dataclass
class Proposal:
    category: str
    new_name: str
    source: str       # 'llm' | 'rule'
    snippet: str


def clean_title(title: str, max_len: int = 70) -> str:
    t = _ILLEGAL.sub(" ", title)
    t = " ".join(t.split()).strip(" .")
    t = t[:max_len].strip(" .")
    if t.upper() in _RESERVED:
        t += "_"
    return t


def build_name(path: Path, title: str | None) -> str:
    if not title:
        return path.name
    title = clean_title(title)
    if not title:
        return path.name
    date = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d")
    return f"{date} {title}{path.suffix.lower()}"


def _prompt(cfg: Config, db: DB, path: Path, content: Content) -> str:
    lines = [
        "You file documents. Reply with ONLY one JSON object: "
        '{"category": "<one of the list>", "title": "<3 to 8 word descriptive title>"}.',
        "Categories: " + ", ".join(cfg.categories) + ".",
        "The title must describe what the file is about (who, what, which month if visible). "
        "No file extension, no quotes inside, no date prefix.",
        f"Original filename: {path.name}",
    ]
    fixes = db.recent_corrections(6)
    if fixes:
        lines.append("The user has corrected you before. Learn from these:")
        for c in fixes:
            hint = f" (it looked like: {c['snippet'][:80]})" if c["snippet"] else ""
            lines.append(f"- '{c['filename']}'{hint} belongs in {c['chosen']}, not {c['proposed']}.")
    if content.text:
        lines.append("Text from the file: " + content.text[:1800])
    if content.image_b64:
        lines.append("An image of the file is attached.")
    return "\n".join(lines)


def _parse(raw: str) -> dict | None:
    m = re.search(r"\{.*?\}", raw, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _match_category(cfg: Config, value: str) -> str:
    v = (value or "").strip().lower()
    for c in cfg.categories:
        if c.lower() == v:
            return c
    for c in cfg.categories:
        if v and (v in c.lower() or c.lower() in v):
            return c
    return "Other"


def _fallback_image_category(cfg: Config, path: Path) -> str:
    n = path.name.lower()
    if n.startswith(("screenshot", "screen shot", "capture", "snip")) and "Screenshots" in cfg.categories:
        return "Screenshots"
    return "Images" if "Images" in cfg.categories else "Other"


def classify(cfg: Config, db: DB, llm: LLM, path: Path) -> Proposal:
    ext = path.suffix.lower()
    content = extract(path, cfg)

    # Files we can't read: sort by extension, keep the original name.
    if ext in RULE_CATEGORY and content.kind in ("binary",):
        cat = RULE_CATEGORY[ext]
        cat = cat if cat in cfg.categories else "Other"
        return Proposal(cat, path.name, "rule", "")

    # An image with vision switched off: filename heuristics only.
    if content.kind == "image" and not content.image_b64:
        return Proposal(_fallback_image_category(cfg, path), path.name, "rule", "")

    if content.kind == "binary":
        return Proposal("Other", path.name, "rule", "")

    try:
        raw = llm.chat(_prompt(cfg, db, path, content), image_b64=content.image_b64)
    except LLMError:
        raise
    data = _parse(raw)
    snippet = (content.text or "")[:200]
    if not data:
        # The model answered, but not in a usable shape: don't guess a name.
        cat = _fallback_image_category(cfg, path) if content.kind == "image" else "Other"
        return Proposal(cat, path.name, "rule", snippet)
    cat = _match_category(cfg, str(data.get("category", "")))
    return Proposal(cat, build_name(path, str(data.get("title", ""))), "llm", snippet)
