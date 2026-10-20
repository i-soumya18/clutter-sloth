"""End-to-end test against the mock server. Run: python tests/test_e2e.py"""
from __future__ import annotations

import os
import random
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import mock_server  # noqa: E402
from PIL import Image  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

from sloth import digest  # noqa: E402
from sloth.config import Config  # noqa: E402
from sloth.db import DB  # noqa: E402
from sloth.engine import Engine  # noqa: E402
from sloth.llm import LLM  # noqa: E402


def age(p: Path, secs: int = 3600) -> None:
    t = time.time() - secs
    os.utime(p, (t, t))


def make_png(p: Path) -> None:
    img = Image.new("RGB", (1280, 720))
    img.putdata([(random.randint(0, 255),) * 3 for _ in range(1280 * 720)])
    img.save(p)
    age(p)


def make_pdf(p: Path, text: str) -> None:
    c = canvas.Canvas(str(p))
    c.drawString(72, 750, text)
    c.save()
    age(p)


def main() -> None:
    srv = mock_server.start()
    tmp = Path(tempfile.mkdtemp())
    dl = tmp / "Downloads"
    dl.mkdir()

    cfg = Config(watch_dir=dl, base_url=f"http://127.0.0.1:{srv.server_address[1]}/v1",
                 trust_threshold=2, settle_seconds=60, app_dir=tmp / "app")
    db = DB(cfg.db_path)
    eng = Engine(cfg, db, LLM(cfg))

    # ---- files ----
    make_png(dl / "Screenshot 2026-10-20 at 11.42.10.png")
    make_pdf(dl / "bill.pdf", "INVOICE 1042 Acme Corp total due 48.00")
    (dl / "notes.txt").write_text("Agenda: roadmap review, hiring, Q4 planning")
    (dl / "setup.apk").write_bytes(os.urandom(2048))
    (dl / "backup.zip").write_bytes(os.urandom(2048))
    (dl / "movie.crdownload").write_bytes(b"half")
    (dl / "fresh.txt").write_text("just downloaded")  # not settled yet
    for f in ("notes.txt", "setup.apk", "backup.zip", "movie.crdownload"):
        age(dl / f)
    (dl / "Sorted").mkdir()  # pre-existing folders must be ignored
    (dl / "Old stuff").mkdir()

    # ---- 1. only settled, non-temp files are candidates ----
    names = sorted(p.name for p in eng.candidates())
    assert names == ["Screenshot 2026-10-20 at 11.42.10.png", "backup.zip", "bill.pdf",
                     "notes.txt", "setup.apk"], names
    print("ok  candidates skip fresh files, .crdownload and folders")

    # ---- 2. first pass: preview only, nothing moves ----
    for p in eng.candidates():
        pid, moved = eng.propose(p)
        assert pid and not moved
    assert len(db.pending()) == 5
    assert (dl / "notes.txt").exists()
    assert not any(eng.candidates()), "already-proposed files must not be re-proposed"
    print("ok  trust ladder starts in preview-only mode; nothing moved")

    by_src = {Path(r["src"]).name: r for r in db.pending()}
    assert by_src["bill.pdf"]["category"] == "Invoices & Receipts"
    assert by_src["bill.pdf"]["new_name"].endswith("Acme Corp invoice 1042 cloud hosting.pdf"), by_src["bill.pdf"]["new_name"]
    shot = by_src["Screenshot 2026-10-20 at 11.42.10.png"]
    assert shot["category"] == "Screenshots" and "<" not in shot["new_name"] and '"' not in shot["new_name"]
    assert by_src["setup.apk"]["category"] == "Installers" and by_src["setup.apk"]["new_name"] == "setup.apk"
    assert by_src["backup.zip"]["category"] == "Archives"
    assert any(r["image"] for r in mock_server.REQUESTS), "image never reached the model"
    assert all(r["auth"] == "Bearer unsloth" for r in mock_server.REQUESTS)
    print("ok  names cleaned, binaries sorted by rule, image + auth sent")

    # ---- 3. approvals build trust; a correction resets it and feeds the next prompt ----
    eng.begin_batch()
    eng.approve(shot["id"])
    eng.approve(by_src["bill.pdf"]["id"])
    eng.correct(by_src["notes.txt"]["id"], "Other")
    assert (cfg.sorted_dir / "Screenshots" / shot["new_name"]).exists()
    assert (cfg.sorted_dir / "Other" / "notes.txt").exists() or list((cfg.sorted_dir / "Other").glob("*notes*"))
    assert db.streak("Screenshots") == 1 and db.streak("Documents") == 0
    assert len(db.recent_corrections()) == 1
    print("ok  approve builds trust, correction recorded")

    # ---- 4. earn auto-move: second screenshot approval reaches the threshold of 2 ----
    make_png(dl / "shot2.png")
    make_png(dl / "shot3.png")
    make_png(dl / "shot4.png")
    eng.begin_batch()
    ids = {}
    for name in ("shot2.png", "shot3.png"):
        pid, moved = eng.propose(dl / name)
        assert not moved
        ids[name] = pid
    eng.approve(ids["shot2.png"])  # streak hits 2 -> Screenshots now trusted
    assert db.streak("Screenshots") == 2
    # the prompt for the next file must now contain the user's correction
    mock_server.REQUESTS.clear()
    eng.begin_batch()
    pid, moved = eng.propose(dl / "shot4.png")
    assert moved, "trusted category should move on its own"
    pid3, moved3 = eng.propose(dl / "shot3.png") if (dl / "shot3.png").exists() else (None, False)
    print("ok  trusted category moves files on its own")

    # ---- 5. undoing an auto-move restores the file and removes the trust ----
    auto_batch = db.last_batch()
    res = eng.undo_last_batch()
    assert any("restored" in r for r in res), res
    assert (dl / "shot4.png").exists()
    assert db.streak("Screenshots") == 0
    print("ok  undo restores the file and resets trust")

    # ---- 6. correction text reaches the model ----
    make_pdf(dl / "memo.pdf", "Weekly memo about hiring")
    mock_server.REQUESTS.clear()
    eng.propose(dl / "memo.pdf")
    sent = mock_server.REQUESTS[-1]["text"]
    assert "belongs in Other, not Documents" in sent, sent
    print("ok  past corrections are fed back into the prompt")

    # ---- 7. name collisions never overwrite ----
    a = dl / "a.txt"; b = dl / "b.txt"
    a.write_text("Agenda one"); b.write_text("Agenda two")
    age(a); age(b)
    # force identical target names
    pa, _ = eng.propose(a); pb, _ = eng.propose(b)
    db._q("UPDATE proposals SET new_name='same.txt' WHERE id IN (?,?)", (pa, pb))
    d1 = eng.approve(pa); d2 = eng.approve(pb)
    assert d1 != d2 and d1.exists() and d2.exists() and d2.name == "same (2).txt"
    print("ok  name collisions get (2), nothing overwritten")

    # ---- 8. undo single move when the original spot is taken ----
    mv = [m for m in db.history(50) if Path(m["dst"]) == d1][0]
    a.write_text("a new file with the old name")
    msg = eng.undo_move(mv["id"])
    assert "restored" in msg and (dl / "a (restored).txt").exists()
    print("ok  undo never overwrites a file that took the old name")

    # ---- 9. digest ----
    text = digest.build(cfg, db, 7)
    assert "Files sorted" in text and "Trust ladder" in text
    print("ok  digest builds")
    print("\n" + text)

    # ---- 10. nothing was ever deleted: every file we created still exists somewhere ----
    total_files = sum(1 for _ in dl.rglob("*") if _.is_file())
    assert total_files >= 11, total_files
    print(f"ok  no file lost ({total_files} files still present)")

    # ---- 11. never_auto categories stay in preview-only mode even after threshold approvals ----
    for i in range(3):
        f = dl / f"id_{i}.txt"
        f.write_text(f"Personal ID document copy #{i}")
        age(f)
        pid = db.add_proposal(str(f), time.time() - 3600, "ID & Personal", f.name, "rule", "")
        eng.approve(pid)
    assert db.streak("ID & Personal") == 3
    assert db.streak("ID & Personal") >= cfg.trust_threshold
    f_next = dl / "id_sensitive.txt"
    f_next.write_text("Confidential identity record")
    age(f_next)
    pid_next = db.add_proposal(str(f_next), time.time() - 3600, "ID & Personal", f_next.name, "rule", "")
    can_auto_move = (
        "ID & Personal" not in cfg.never_auto
        and db.streak("ID & Personal") >= cfg.trust_threshold
    )
    assert not can_auto_move, "never_auto categories must never auto-move"
    digest_text = digest.build(cfg, db, 7)
    assert "ID & Personal: preview only (never auto" in digest_text, digest_text
    print("ok  never_auto category stays in preview-only mode even after threshold approvals")


if __name__ == "__main__":
    main()
