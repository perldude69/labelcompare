from pathlib import Path

import pytest

from server.pdf import sanitize_pdf_bytes, render_pages

APPS = Path(__file__).resolve().parent.parent / "applications"


def test_sanitize_strips_junk_prefix():
    data = b"<b>Notice</b>: php junk\n%PDF-1.4 rest of file"
    assert sanitize_pdf_bytes(data) == b"%PDF-1.4 rest of file"


def test_sanitize_passthrough_clean_pdf():
    data = b"%PDF-1.4 rest"
    assert sanitize_pdf_bytes(data) == data


def test_sanitize_rejects_non_pdf():
    with pytest.raises(ValueError):
        sanitize_pdf_bytes(b"GIF89a not a pdf at all" * 100)


def test_render_pages_cies():
    raw = (APPS / "cies.pdf").read_bytes()
    pages = render_pages(raw, dpi=72)
    assert len(pages) == 3
    assert all(p.startswith(b"\x89PNG") for p in pages)


def test_render_pages_scan():
    raw = (APPS / "ABCWine-scan.pdf").read_bytes()
    pages = render_pages(raw, dpi=72)
    assert len(pages) == 1
