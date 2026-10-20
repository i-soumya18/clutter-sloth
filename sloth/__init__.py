"""Clutter Sloth: a slow, careful, local-only Downloads folder sorter."""
import sys

# Ensure safe UTF-8 terminal I/O on Windows consoles without requiring python -X utf8
for _stream_name in ("stdout", "stderr", "stdin"):
    _stream = getattr(sys, _stream_name, None)
    if _stream and hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

__version__ = "0.1.0"
