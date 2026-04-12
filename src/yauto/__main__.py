import sys

# Ensure stdin/stdout can handle any byte sequence without crashing.
# Minimal VPS setups often have broken locale (e.g. LANG=C), which makes
# Python's default UTF-8 stdin choke on Cyrillic or other multi-byte input.
for _stream_name in ("stdin", "stdout", "stderr"):
    _stream = getattr(sys, _stream_name, None)
    if _stream and hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

from yauto.cli.app import main


if __name__ == "__main__":
    main()
