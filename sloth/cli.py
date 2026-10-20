"""Command line: sloth init | doctor | run | scan | review | undo | history | digest | status"""
from __future__ import annotations

import argparse
import logging
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from . import __version__, digest
from .config import APP_DIR, CONFIG_PATH, DEFAULT_TOML, load
from .db import DB
from .engine import Engine
from .llm import LLM, LLMError
from .worker import run_forever


def _engine(args) -> Engine:
    cfg = load(args.config)
    if getattr(args, "watch", None):
        cfg.watch_dir = Path(args.watch).expanduser()
        cfg.sorted_dir = cfg.watch_dir / "Sorted"
    return Engine(cfg, DB(cfg.db_path), LLM(cfg))


def cmd_init(args) -> int:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_PATH.exists() and not args.force:
        print(f"Config already exists: {CONFIG_PATH}  (use --force to overwrite)")
        return 0
    CONFIG_PATH.write_text(DEFAULT_TOML, encoding="utf-8")
    print(f"Wrote {CONFIG_PATH}\nEdit base_url / api_key to match Unsloth, then run: sloth doctor")
    return 0


def cmd_doctor(args) -> int:
    eng = _engine(args)
    cfg = eng.cfg
    print(f"Watching      : {cfg.watch_dir}  (exists: {cfg.watch_dir.exists()})")
    print(f"Sorted files  : {cfg.sorted_dir}")
    print(f"Model server  : {cfg.base_url}")
    try:
        ids = eng.llm.models()
    except LLMError as e:
        print(f"  x {e}\n  Open Unsloth, load a model, and start its local server/API. "
              "Check the port and API key in the app, then update config.toml.")
        return 1
    print(f"  ok, models reported: {', '.join(ids) or '(none loaded)'}")
    if not ids:
        return 1
    try:
        reply = eng.llm.chat('Reply with exactly: {"ok": true}', max_tokens=20)
        print(f"  ok, test reply: {reply.strip()[:60]}")
    except LLMError as e:
        print(f"  x {e}")
        return 1
    return 0


def cmd_scan(args) -> int:
    """One pass over the folder right now (ignores the settle timer with --now)."""
    t0 = time.time()
    eng = _engine(args)
    files = eng.candidates(force=args.now)
    if not files:
        print("Nothing new and settled to look at.")
        return 0
    eng.begin_batch()
    auto = queued = 0
    for p in files:
        try:
            pid, moved = eng.propose(p)
        except LLMError as e:
            print(f"Model unavailable: {e}")
            return 1
        if pid:
            auto += moved
            queued += not moved
            print(f"  {'moved ' if moved else 'queued'}  {p.name}")
    elapsed = time.time() - t0
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)
    duration_str = f"{minutes}m {seconds}s" if minutes else f"{seconds}s"
    print(f"\n{auto} moved on their own, {queued} waiting for review ({duration_str} total). Run: sloth review")
    return 0


def cmd_run(args) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    eng = _engine(args)
    stop = threading.Event()
    try:
        run_forever(eng, stop)
    except KeyboardInterrupt:
        stop.set()
        print("\nStopped.")
    return 0


def cmd_review(args) -> int:
    eng = _engine(args)
    cfg, db = eng.cfg, eng.db
    rows = db.pending()
    if not rows:
        print("Nothing waiting for review.")
        return 0
    eng.begin_batch()
    print(f"{len(rows)} waiting.  [Enter]=approve  n=leave it  c=change category  q=quit\n")
    for row in rows:
        src = Path(row["src"])
        if not src.exists():
            db.set_status(row["id"], "gone")
            continue
        left = db.streak(row["category"])
        tag = "name+category" if row["source"] == "llm" else "category only"
        if row["category"] in cfg.never_auto:
            trust_info = f"never auto, {left} approvals"
        else:
            trust_info = f"trust {left}/{cfg.trust_threshold}"
        print(f"{src.name}\n   -> {row['category']}/{row['new_name']}   ({tag}, {trust_info})")
        while True:
            ans = input("   > ").strip().lower()
            if ans in ("", "y"):
                eng.approve(row["id"])
                print("   moved.")
                break
            if ans == "n":
                eng.reject(row["id"])
                print("   left in place.")
                break
            if ans == "c":
                for i, c in enumerate(cfg.categories, 1):
                    print(f"     {i}. {c}")
                pick = input("   category number > ").strip()
                if pick.isdigit() and 1 <= int(pick) <= len(cfg.categories):
                    eng.correct(row["id"], cfg.categories[int(pick) - 1])
                    print("   moved, and noted for next time.")
                    break
                print("   not a valid number.")
                continue
            if ans == "q":
                print("Stopped. The rest stay queued.")
                return 0
    return 0


def cmd_undo(args) -> int:
    eng = _engine(args)
    if args.id:
        print(eng.undo_move(args.id))
        return 0
    results = eng.undo_last_batch()
    if not results:
        print("Nothing to undo.")
    for r in results:
        print(" ", r)
    return 0


def cmd_history(args) -> int:
    eng = _engine(args)
    for m in eng.db.history(args.limit):
        when = datetime.fromtimestamp(m["ts"]).strftime("%m-%d %H:%M")
        flag = " (undone)" if m["undone"] else ""
        print(f"#{m['id']:<4} batch {m['batch']:<3} {when}  {m['how']:<9} "
              f"{Path(m['src']).name}  ->  {m['category']}/{Path(m['dst']).name}{flag}")
    return 0


def cmd_digest(args) -> int:
    eng = _engine(args)
    text, path = digest.write(eng.cfg, eng.db, args.days)
    print(text)
    print(f"(saved to {path})")
    return 0


def cmd_status(args) -> int:
    eng = _engine(args)
    streaks = eng.db.all_streaks()
    print(f"Pending review: {len(eng.db.pending())}")
    for cat in eng.cfg.categories:
        st = streaks.get(cat, 0)
        if cat in eng.cfg.never_auto:
            state = f"never auto ({st} approvals)"
        elif st >= eng.cfg.trust_threshold:
            state = "moves on its own"
        else:
            state = f"preview only ({st}/{eng.cfg.trust_threshold})"
        print(f"  {cat:<22} {state}")
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream_name in ("stdout", "stderr", "stdin"):
        stream = getattr(sys, stream_name, None)
        if stream and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

    ap = argparse.ArgumentParser(prog="sloth", description="Slow, careful, local-only Downloads sorter.")
    ap.add_argument("--version", action="version", version=__version__)
    ap.add_argument("--config", help="path to config.toml")
    ap.add_argument("--watch", help="override the folder to tidy (handy for trying it out)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="write a starter config")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_init)
    sub.add_parser("doctor", help="check the folder and the Unsloth server").set_defaults(fn=cmd_doctor)
    sub.add_parser("run", help="watch the folder and work slowly in the background").set_defaults(fn=cmd_run)
    p = sub.add_parser("scan", help="look at the folder once, right now")
    p.add_argument("--now", action="store_true", help="skip the settle timer")
    p.set_defaults(fn=cmd_scan)
    sub.add_parser("review", help="approve, change, or skip queued moves").set_defaults(fn=cmd_review)
    p = sub.add_parser("undo", help="undo the last batch of moves")
    p.add_argument("--id", type=int, help="undo a single move by id (see history)")
    p.set_defaults(fn=cmd_undo)
    p = sub.add_parser("history", help="list recent moves")
    p.add_argument("--limit", type=int, default=30)
    p.set_defaults(fn=cmd_history)
    p = sub.add_parser("digest", help="summary of what moved")
    p.add_argument("--days", type=int, default=7)
    p.set_defaults(fn=cmd_digest)
    sub.add_parser("status", help="pending count and trust per category").set_defaults(fn=cmd_status)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
