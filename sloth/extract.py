"""Turn a file into something a small local model can read: text and/or one downscaled image."""
from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from pathlib import Path

from .config import Config

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
TEXT_EXT = {".txt", ".md", ".csv", ".json", ".log", ".html", ".xml", ".yml", ".yaml", ".rtf"}
CODE_EXT = {".py", ".js", ".ts", ".java", ".c", ".cpp", ".cs", ".go", ".rs", ".sql", ".ipynb"}
PDF_EXT = {".pdf"}

# Things we can't usefully "read": sort by extension and leave the name alone.
RULE_CATEGORY = {
    ".exe": "Installers", ".msi": "Installers", ".apk": "Installers", ".dmg": "Installers",
    ".msix": "Installers", ".deb": "Installers",
    ".zip": "Archives", ".rar": "Archives", ".7z": "Archives", ".tar": "Archives",
    ".gz": "Archives", ".iso": "Archives",
    ".mp4": "Media", ".mkv": "Media", ".mov": "Media", ".avi": "Media",
    ".mp3": "Media", ".wav": "Media", ".flac": "Media", ".m4a": "Media",
    ".xlsx": "Documents", ".docx": "Documents", ".pptx": "Documents",
    **{e: "Code & Data" for e in CODE_EXT},
}

# Half-downloaded or in-use files: never touch.
SKIP_EXT = {".crdownload", ".part", ".tmp", ".download", ".opdownload", ".partial"}
SKIP_NAMES = {"desktop.ini", "thumbs.db", ".ds_store"}


@dataclass
class Content:
    kind: str                    # image | pdf | text | binary
    text: str = ""
    image_b64: str | None = None


def _encode_image(img, max_side: int) -> str:
    from PIL import Image

    img = img.convert("RGB")
    img.thumbnail((max_side, max_side), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return base64.b64encode(buf.getvalue()).decode()


def _pdf_text(path: Path, pages: int = 2, limit: int = 2500) -> str:
    from pypdf import PdfReader

    # Read via an explicit handle so the file is closed before we try to move it (matters on Windows).
    with open(path, "rb") as f:
        reader = PdfReader(f)
        out = [page.extract_text() or "" for page in reader.pages[:pages]]
    return " ".join(" ".join(out).split())[:limit]


def _pdf_first_page_image(path: Path, max_side: int) -> str | None:
    pdf = page = None
    try:
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(str(path))
        page = pdf[0]
        pil = page.render(scale=1.4).to_pil()
        return _encode_image(pil, max_side)
    except Exception:
        return None
    finally:
        # An open PDF handle blocks moving the file on Windows.
        for obj in (page, pdf):
            try:
                if obj is not None:
                    obj.close()
            except Exception:
                pass


def extract(path: Path, cfg: Config) -> Content:
    ext = path.suffix.lower()
    try:
        if ext in IMAGE_EXT:
            from PIL import Image

            with Image.open(path) as img:
                b64 = _encode_image(img, cfg.max_image_side) if cfg.vision else None
            return Content("image", image_b64=b64)

        if ext in PDF_EXT:
            text = _pdf_text(path)
            image = None
            if len(text) < 40 and cfg.vision:   # probably a scan
                image = _pdf_first_page_image(path, cfg.max_image_side)
            return Content("pdf", text=text, image_b64=image)

        if ext in TEXT_EXT:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return Content("text", text=" ".join(f.read(4000).split())[:2500])
    except Exception:
        pass
    return Content("binary")
