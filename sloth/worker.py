"""The sloth loop: wake on new files, wait for them to settle, then work slowly at low priority."""
from __future__ import annotations

import logging
import os
import threading
import time

import psutil

from .engine import Engine
from .llm import LLMError

log = logging.getLogger("sloth")


def lower_priority() -> None:
    try:
        p = psutil.Process(os.getpid())
        if os.name == "nt":
            p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
        else:
            p.nice(10)
    except Exception:
        pass


def wait_for_calm(ceiling: float, stop: threading.Event, max_wait: float = 600) -> None:
    """Block while the machine is busy. Gives up after max_wait so we never starve forever."""
    waited = 0.0
    while not stop.is_set() and waited < max_wait:
        if psutil.cpu_percent(interval=1.0) < ceiling:
            return
        waited += 1.0
        stop.wait(4.0)
        waited += 4.0


def start_watcher(engine: Engine, wake: threading.Event):
    """File-system events just wake the worker; the settle timer decides when a file is ready."""
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer

    class Handler(FileSystemEventHandler):
        def on_created(self, event):
            if not event.is_directory:
                wake.set()

        def on_moved(self, event):
            if not event.is_directory:
                wake.set()

    obs = Observer()
    obs.schedule(Handler(), str(engine.cfg.watch_dir), recursive=False)
    obs.start()
    return obs


def run_forever(engine: Engine, stop: threading.Event | None = None) -> None:
    stop = stop or threading.Event()
    wake = threading.Event()
    lower_priority()
    observer = start_watcher(engine, wake)
    cfg = engine.cfg
    log.info("Watching %s (settle %ss, trust after %s approvals)",
             cfg.watch_dir, cfg.settle_seconds, cfg.trust_threshold)
    try:
        while not stop.is_set():
            files = engine.candidates()
            if not files:
                wake.wait(timeout=max(15, cfg.settle_seconds / 2))
                wake.clear()
                continue
            engine.begin_batch()
            for path in files:
                if stop.is_set():
                    break
                wait_for_calm(cfg.cpu_ceiling, stop)
                try:
                    pid, auto = engine.propose(path)
                    if pid:
                        log.info("%s %s", "moved" if auto else "queued", path.name)
                except LLMError as e:
                    log.warning("Model unavailable (%s). Will retry later.", e)
                    stop.wait(60)
                    break
                except Exception as e:  # one bad file must never stop the loop
                    log.exception("Skipping %s: %s", path.name, e)
                stop.wait(cfg.pause_between_files)
    finally:
        observer.stop()
        observer.join(timeout=5)
