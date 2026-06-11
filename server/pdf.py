"""PDF sanitizing and page rendering."""
import fitz

# How far into a file we look for the %PDF header (matches upload validation).
HEADER_SEARCH_LIMIT = 1024


def sanitize_pdf_bytes(data: bytes) -> bytes:
    """Strip junk bytes before the %PDF header (e.g. PHP error HTML)."""
    idx = data.find(b"%PDF", 0, HEADER_SEARCH_LIMIT)
    if idx == -1:
        raise ValueError("not a PDF: no %PDF header in first 1KB")
    return data[idx:]


def render_page_views(data: bytes, dpi: int = 150) -> list[list[bytes]]:
    """Per page: full render plus top/bottom halves with 5% overlap.

    The OCR model tends to skip columns in dense form regions when given
    a whole page; the half-page tiles guarantee coverage, while the
    full-page view keeps paragraphs that straddle the midline intact.
    """
    clean = sanitize_pdf_bytes(data)
    doc = fitz.open(stream=clean, filetype="pdf")
    pages = []
    for page in doc:
        r = page.rect
        mid, overlap = r.height / 2, r.height * 0.05
        views = [page.get_pixmap(dpi=dpi).tobytes("png")]
        for clip in (fitz.Rect(0, 0, r.width, mid + overlap),
                     fitz.Rect(0, mid - overlap, r.width, r.height)):
            views.append(page.get_pixmap(dpi=dpi, clip=clip).tobytes("png"))
        pages.append(views)
    doc.close()
    return pages


def render_pages(data: bytes, dpi: int = 150) -> list[bytes]:
    """Render every page of a PDF to PNG bytes."""
    clean = sanitize_pdf_bytes(data)
    doc = fitz.open(stream=clean, filetype="pdf")
    pages = []
    for page in doc:
        pix = page.get_pixmap(dpi=dpi)
        pages.append(pix.tobytes("png"))
    doc.close()
    return pages
