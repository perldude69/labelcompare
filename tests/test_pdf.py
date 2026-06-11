import io

import fitz
import pytest
from PIL import Image

from server.pdf import (preprocess_for_ocr, render_page_views, render_pages,
                        sanitize_pdf_bytes)


def make_pdf(n_pages=1, width=200, height=400):
    doc = fitz.open()
    for i in range(n_pages):
        page = doc.new_page(width=width, height=height)
        page.insert_text((20, 30), f"TOP OF PAGE {i + 1}")
        page.insert_text((20, height - 20), f"BOTTOM OF PAGE {i + 1}")
    data = doc.tobytes()
    doc.close()
    return data


def png_size(data):
    return Image.open(io.BytesIO(data)).size


def test_sanitize_strips_junk_prefix():
    data = b"<b>Notice</b>: php junk\n%PDF-1.4 rest of file"
    assert sanitize_pdf_bytes(data) == b"%PDF-1.4 rest of file"


def test_sanitize_passthrough_clean_pdf():
    data = b"%PDF-1.4 rest"
    assert sanitize_pdf_bytes(data) == data


def test_sanitize_rejects_non_pdf():
    with pytest.raises(ValueError):
        sanitize_pdf_bytes(b"GIF89a not a pdf at all" * 100)


def test_render_pages_counts_pages():
    pages = render_pages(make_pdf(3), dpi=72)
    assert len(pages) == 3
    assert all(p.startswith(b"\x89PNG") for p in pages)


def test_render_page_views_covers_top_and_bottom():
    """Every page needs a dedicated high-detail crop of BOTH the upper and the
    lower region: the OCR model skips dense columns on full-page views, and a
    GOVERNMENT WARNING in the bottom third must not depend on the full view."""
    pages = render_page_views(make_pdf(1), dpi=72)
    assert len(pages) == 1
    views = pages[0]
    assert len(views) == 3  # full + upper crop + lower crop
    full_w, full_h = png_size(views[0])
    upper_w, upper_h = png_size(views[1])
    lower_w, lower_h = png_size(views[2])
    assert upper_w == full_w and lower_w == full_w
    # Crops are real crops (more detail per region), not the whole page again
    assert upper_h < full_h and lower_h < full_h
    # Together (with overlap) the two crops span the full page height
    assert upper_h + lower_h >= full_h


def test_preprocess_for_ocr_outputs_grayscale_jpeg():
    views = render_page_views(make_pdf(1), dpi=72)
    out = preprocess_for_ocr(views[0][0])
    assert out.startswith(b"\xff\xd8")  # JPEG magic
    img = Image.open(io.BytesIO(out))
    assert img.mode == "L"


def test_preprocess_for_ocr_caps_size():
    big = render_page_views(make_pdf(1, width=600, height=1200), dpi=300)
    out = preprocess_for_ocr(big[0][0], max_side=1400)
    img = Image.open(io.BytesIO(out))
    assert max(img.size) <= 1400
