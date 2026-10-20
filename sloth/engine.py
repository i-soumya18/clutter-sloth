"""The brain: find settled files, propose moves, apply them, undo them, and run the trust ladder."""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from .classify import classify
from .config import Config
from .db import DB
from .extract import SKIP_EXT, SKIP_NAMES
from .llm import LLM


def unique_path(p: Path) -> Path:
    if not p.exists():
        return p
    i = 2
    while True:
        cand = p.with_name(f"{p.stem} ({i}){p.suffix}")
        if not cand.exists():
            return cand
        i += 1


class Engine:
    def __init__(self, cfg: Config, db: DB, llm: LLM | None = None):
        self.cfg = cfg
        self.db = db
        self.llm = llm or LLM(cfg)
        self.batch = db.new_batch()

    # ---------- finding work ----------
    def begin_batch(self) -> int:
        self.batch = self.db.new_batch()
        return self.batch

    def candidates(self, force: bool = False) -> list[Path]:
        """Top-level files that are finished downloading and not seen before."""
        out: list[Path] = []
        now = time.time()
        if not self.cfg.watch_dir.exists():
            return out
        for p in sorted(self.cfg.watch_dir.iterdir()):
            try:
                if not p.is_file() or p.name.startswith("."):
                    continue
                if p.suffix.lower() in SKIP_EXT or p.name.lower() in SKIP_NAMES:
                    continue
                st = p.stat()
                if not force and now - st.st_mtime < self.cfg.settle_seconds:
                    continue
                if self.db.seen(str(p), st.st_mtime):
                    continue
                out.append(p)
            except OSError:
                continue
        return out

    # ---------- proposing ----------
    def propose(self, path: Path) -> tuple[int | None, bool]:
        """Classify one file. Returns (proposal id, moved_automatically)."""
        st = path.stat()
        prop = classify(self.cfg, self.db, self.llm, path)
        pid = self.db.add_proposal(str(path), st.st_mtime, prop.category, prop.new_name,
                                   prop.source, prop.snippet)
        if pid is None:
            return None, False
        if (
            prop.category not in self.cfg.never_auto
            and self.db.streak(prop.category) >= self.cfg.trust_threshold
        ):
            self.apply(pid, how="auto")
            return pid, True
        return pid, False

    # ---------- applying ----------
    def _dest(self, category: str, name: str) -> Path:
        d = self.cfg.sorted_dir / category
        d.mkdir(parents=True, exist_ok=True)
        return unique_path(d / name)

    def apply(self, pid: int, how: str, category: str | None = None) -> Path | None:
        row = self.db.get_proposal(pid)
        if row is None or row["status"] != "pending":
            return None
        src = Path(row["src"])
        if not src.exists():
            self.db.set_status(pid, "gone")
            return None
        cat = category or row["category"]
        dst = self._dest(cat, row["new_name"])
        shutil.move(str(src), str(dst))
        self.db.record_move(self.batch, str(src), str(dst), cat, how)
        self.db.set_status(pid, "done")
        return dst

    def approve(self, pid: int) -> Path | None:
        row = self.db.get_proposal(pid)
        dst = self.apply(pid, how="approved")
        if dst is not None:
            self.db.approve(row["category"])
        return dst

    def correct(self, pid: int, new_category: str) -> Path | None:
        row = self.db.get_proposal(pid)
        dst = self.apply(pid, how="corrected", category=new_category)
        if dst is not None:
            self.db.add_correction(Path(row["src"]).name, row["snippet"], row["category"], new_category)
            self.db.demote(row["category"])
        return dst

    def reject(self, pid: int) -> None:
        """Leave the file where it is, and don't propose this version of it again."""
        self.db.set_status(pid, "rejected")

    # ---------- undo ----------
    def undo_move(self, move_id: int) -> str:
        mv = self.db.get_move(move_id)
        if mv is None or mv["undone"]:
            return "nothing to undo"
        src, dst = Path(mv["src"]), Path(mv["dst"])
        if not dst.exists():
            return f"missing: {dst.name} is no longer where it was put"
        target = src
        if target.exists():
            target = src.with_name(f"{src.stem} (restored){src.suffix}")
            target = unique_path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(dst), str(target))
        self.db.mark_undone(move_id)
        if mv["how"] == "auto":
            # Undoing an automatic move is a clear "I didn't want that": lose the trust.
            self.db.demote(mv["category"])
            self.db.add_correction(src.name, "", mv["category"], "(undone)")
        return f"restored {target.name}"

    def undo_last_batch(self) -> list[str]:
        batch = self.db.last_batch()
        if batch is None:
            return []
        return [self.undo_move(m["id"]) for m in self.db.batch_moves(batch)]
