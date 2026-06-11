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
