"""Configuration: a flat TOML file in ~/.clutter-sloth/config.toml."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

HOME = Path.home()
APP_DIR = HOME / ".clutter-sloth"
CONFIG_PATH = APP_DIR / "config.toml"

DEFAULT_CATEGORIES = [
    "Screenshots",
    "Invoices & Receipts",
    "ID & Personal",
    "Tickets & Travel",
    "Research Papers",
    "Resumes",
    "Documents",
    "Images",
    "Installers",
    "Archives",
    "Code & Data",
    "Media",
    "Other",
]

DEFAULT_NEVER_AUTO = [
    "ID & Personal",
]

DEFAULT_TOML = '''\
# Clutter Sloth config. Every value here is optional.

# Folder to tidy (top-level files only; subfolders are never touched).
watch_dir = "~/Downloads"

# Where sorted files go. Default: <watch_dir>/Sorted
# sorted_dir = "~/Downloads/Sorted"

# Unsloth Desktop / Studio local server (OpenAI-compatible).
# Check the port in the app and change it here if it differs.
base_url = "http://127.0.0.1:8888/v1"
api_key  = "unsloth"          # use the key shown in the app, if it asks for one
model    = ""                 # empty = use the first model the server reports

# Send images (and scanned PDFs) to the model. Needs a vision model loaded.
vision = true

# --- Being slow on purpose ---
settle_seconds = 120          # a file must sit untouched this long before we look at it
pause_between_files = 5       # seconds of rest between files
cpu_ceiling = 60              # wait while CPU use is above this percent

# --- Trust ladder ---
# A category starts in preview-only mode. After this many approvals in a row
# (with no correction) it moves files on its own. Any correction or undo resets it.
trust_threshold = 5

# Categories that NEVER move on their own, even after many approvals.
# Sensitive files (passports, tax forms, identity cards) should always be reviewed.
never_auto = ["ID & Personal"]

# Image size sent to the model (longest side, pixels). Smaller = easier on 4 GB VRAM.
max_image_side = 768
request_timeout = 300

categories = [
  "Screenshots", "Invoices & Receipts", "ID & Personal", "Tickets & Travel",
  "Research Papers", "Resumes", "Documents", "Images",
  "Installers", "Archives", "Code & Data", "Media", "Other",
]
'''


@dataclass
class Config:
    watch_dir: Path = HOME / "Downloads"
    sorted_dir: Path | None = None
    base_url: str = "http://127.0.0.1:8888/v1"
    api_key: str = "unsloth"
    model: str = ""
    vision: bool = True
    settle_seconds: int = 120
    pause_between_files: float = 5.0
    cpu_ceiling: float = 60.0
    trust_threshold: int = 5
    never_auto: list[str] = field(default_factory=lambda: list(DEFAULT_NEVER_AUTO))
    max_image_side: int = 768
    request_timeout: int = 300
    categories: list[str] = field(default_factory=lambda: list(DEFAULT_CATEGORIES))
    app_dir: Path = APP_DIR

    def __post_init__(self) -> None:
        self.watch_dir = Path(self.watch_dir).expanduser()
        self.app_dir = Path(self.app_dir).expanduser()
        self.sorted_dir = (
            Path(self.sorted_dir).expanduser() if self.sorted_dir else self.watch_dir / "Sorted"
        )
        if "Other" not in self.categories:
            self.categories.append("Other")
        self.never_auto = list(self.never_auto)

    @property
    def db_path(self) -> Path:
        return self.app_dir / "sloth.db"

    @property
    def digest_dir(self) -> Path:
        return self.app_dir / "digests"


def load(path: Path | str | None = None) -> Config:
    p = Path(path).expanduser() if path else CONFIG_PATH
    if not p.exists():
        return Config()
    with open(p, "rb") as f:
        raw = tomllib.load(f)
    known = {k: v for k, v in raw.items() if k in Config.__dataclass_fields__}
    return Config(**known)
