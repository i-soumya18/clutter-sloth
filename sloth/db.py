"""SQLite storage: proposals, the undo log, corrections, and per-category trust."""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS proposals(
  id INTEGER PRIMARY KEY,
  src TEXT NOT NULL,
  mtime REAL NOT NULL,
  category TEXT NOT NULL,
  new_name TEXT NOT NULL,
  source TEXT NOT NULL,          -- 'llm' or 'rule'
  snippet TEXT NOT NULL DEFAULT '',
  created REAL NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',   -- pending | done | rejected | gone
  UNIQUE(src, mtime)
);
CREATE TABLE IF NOT EXISTS moves(
  id INTEGER PRIMARY KEY,
  batch INTEGER NOT NULL,
  src TEXT NOT NULL,
  dst TEXT NOT NULL,
  category TEXT NOT NULL,
  how TEXT NOT NULL,             -- auto | approved | corrected
  ts REAL NOT NULL,
  undone INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS corrections(
  id INTEGER PRIMARY KEY,
  ts REAL NOT NULL,
  filename TEXT NOT NULL,
  snippet TEXT NOT NULL DEFAULT '',
  proposed TEXT NOT NULL,
  chosen TEXT NOT NULL           -- a category, or '(undone)'
);
CREATE TABLE IF NOT EXISTS trust(
  category TEXT PRIMARY KEY,
  streak INTEGER NOT NULL DEFAULT 0
);
"""


class DB:
    def __init__(self, path: Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        with self._lock:
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    def _q(self, sql: str, args: tuple = ()):
        with self._lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur

    # ---- proposals ----
    def add_proposal(self, src: str, mtime: float, category: str, new_name: str,
                     source: str, snippet: str) -> int | None:
        try:
            cur = self._q(
                "INSERT INTO proposals(src,mtime,category,new_name,source,snippet,created) "
                "VALUES(?,?,?,?,?,?,?)",
                (src, mtime, category, new_name, source, snippet[:300], time.time()),
            )
            return cur.lastrowid
        except sqlite3.IntegrityError:
            return None

    def seen(self, src: str, mtime: float) -> bool:
        r = self._q("SELECT 1 FROM proposals WHERE src=? AND mtime=?", (src, mtime)).fetchone()
        return r is not None

    def get_proposal(self, pid: int):
        return self._q("SELECT * FROM proposals WHERE id=?", (pid,)).fetchone()

    def pending(self):
        return self._q("SELECT * FROM proposals WHERE status='pending' ORDER BY id").fetchall()

    def set_status(self, pid: int, status: str) -> None:
        self._q("UPDATE proposals SET status=? WHERE id=?", (status, pid))

    # ---- moves / undo log ----
    def new_batch(self) -> int:
        r = self._q("SELECT COALESCE(MAX(batch),0) AS b FROM moves").fetchone()
        return int(r["b"]) + 1

    def record_move(self, batch: int, src: str, dst: str, category: str, how: str) -> int:
        cur = self._q(
            "INSERT INTO moves(batch,src,dst,category,how,ts) VALUES(?,?,?,?,?,?)",
            (batch, src, dst, category, how, time.time()),
        )
        return cur.lastrowid

    def last_batch(self) -> int | None:
        r = self._q("SELECT MAX(batch) AS b FROM moves WHERE undone=0").fetchone()
        return r["b"]

    def batch_moves(self, batch: int):
        return self._q(
            "SELECT * FROM moves WHERE batch=? AND undone=0 ORDER BY id DESC", (batch,)
        ).fetchall()

    def get_move(self, mid: int):
        return self._q("SELECT * FROM moves WHERE id=?", (mid,)).fetchone()

    def mark_undone(self, mid: int) -> None:
        self._q("UPDATE moves SET undone=1 WHERE id=?", (mid,))

    def history(self, limit: int = 30):
        return self._q("SELECT * FROM moves ORDER BY id DESC LIMIT ?", (limit,)).fetchall()

    # ---- corrections ----
    def add_correction(self, filename: str, snippet: str, proposed: str, chosen: str) -> None:
        self._q(
            "INSERT INTO corrections(ts,filename,snippet,proposed,chosen) VALUES(?,?,?,?,?)",
            (time.time(), filename, snippet[:200], proposed, chosen),
        )

    def recent_corrections(self, n: int = 8):
        return self._q(
            "SELECT * FROM corrections WHERE chosen!='(undone)' ORDER BY id DESC LIMIT ?", (n,)
        ).fetchall()

    # ---- trust ladder ----
    def streak(self, category: str) -> int:
        r = self._q("SELECT streak FROM trust WHERE category=?", (category,)).fetchone()
        return int(r["streak"]) if r else 0

    def approve(self, category: str) -> int:
        self._q(
            "INSERT INTO trust(category,streak) VALUES(?,1) "
            "ON CONFLICT(category) DO UPDATE SET streak=streak+1",
            (category,),
        )
        return self.streak(category)

    def demote(self, category: str) -> None:
        self._q(
            "INSERT INTO trust(category,streak) VALUES(?,0) "
            "ON CONFLICT(category) DO UPDATE SET streak=0",
            (category,),
        )

    def all_streaks(self) -> dict[str, int]:
        return {r["category"]: int(r["streak"]) for r in self._q("SELECT * FROM trust")}

    # ---- stats for the digest ----
    def stats(self, since_ts: float) -> dict:
        moved = self._q(
            "SELECT category, how, COUNT(*) AS n FROM moves WHERE ts>=? AND undone=0 "
            "GROUP BY category, how", (since_ts,)
        ).fetchall()
        undone = self._q(
            "SELECT COUNT(*) AS n FROM moves WHERE ts>=? AND undone=1", (since_ts,)
        ).fetchone()["n"]
        corrections = self._q(
            "SELECT COUNT(*) AS n FROM corrections WHERE ts>=? AND chosen!='(undone)'", (since_ts,)
        ).fetchone()["n"]
        pending = self._q("SELECT COUNT(*) AS n FROM proposals WHERE status='pending'").fetchone()["n"]
        return {"moved": [dict(r) for r in moved], "undone": undone,
                "corrections": corrections, "pending": pending}
