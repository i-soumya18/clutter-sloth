"""Weekly digest: what moved, what you corrected, and how much each category is trusted."""
from __future__ import annotations

import time
from datetime import datetime

from .config import Config
from .db import DB


def build(cfg: Config, db: DB, days: int = 7) -> str:
    since = time.time() - days * 86400
    s = db.stats(since)
    by_cat: dict[str, dict[str, int]] = {}
    totals = {"auto": 0, "approved": 0, "corrected": 0}
    for r in s["moved"]:
        by_cat.setdefault(r["category"], {})[r["how"]] = r["n"]
        totals[r["how"]] = totals.get(r["how"], 0) + r["n"]
    moved = sum(totals.values())
    decisions = totals["approved"] + totals["corrected"]
    rate = f"{totals['corrected'] / decisions:.0%}" if decisions else "n/a"

    out = [f"# Clutter Sloth digest, last {days} days ({datetime.now():%Y-%m-%d})", ""]
    out.append(f"Files sorted: **{moved}** "
               f"({totals['auto']} on their own, {totals['approved']} approved, "
               f"{totals['corrected']} corrected by you)")
    out.append(f"Moves you undid: {s['undone']}")
    out.append(f"Correction rate on files you reviewed: {rate}")
    out.append(f"Waiting for your review: {s['pending']}")
    out.append("")
    if by_cat:
        out.append("## By category")
        for cat, hows in sorted(by_cat.items(), key=lambda kv: -sum(kv[1].values())):
            parts = ", ".join(f"{n} {h}" for h, n in hows.items())
            out.append(f"- {cat}: {sum(hows.values())} ({parts})")
        out.append("")
    streaks = db.all_streaks()
    out.append("## Trust ladder")
    for cat in cfg.categories:
        st = streaks.get(cat, 0)
        if cat in cfg.never_auto:
            state = f"preview only (never auto, {st} approvals)"
        elif st >= cfg.trust_threshold:
            state = "moves on its own"
        else:
            state = f"preview only ({st}/{cfg.trust_threshold})"
        out.append(f"- {cat}: {state}")
    out.append("")
    return "\n".join(out)


def write(cfg: Config, db: DB, days: int = 7) -> tuple[str, str]:
    text = build(cfg, db, days)
    cfg.digest_dir.mkdir(parents=True, exist_ok=True)
    path = cfg.digest_dir / f"{datetime.now():%Y-%m-%d}.md"
    path.write_text(text, encoding="utf-8")
    return text, str(path)
