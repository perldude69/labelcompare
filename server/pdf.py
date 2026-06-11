"""PDF sanitizing and page rendering."""
import fitz
import io
from PIL import Image, ImageEnhance, ImageFilter

# How far into a file we look for the %PDF header (matches upload validation).
HEADER_SEARCH_LIMIT = 1024


def sanitize_pdf_bytes(data: bytes) -> bytes:
    """Strip junk bytes before the %PDF header (e.g. PHP error HTML)."""
    idx = data.find(b"%PDF", 0, HEADER_SEARCH_LIMIT)
    if idx == -1:
        raise ValueError("not a PDF: no %PDF header in first 1KB")
    return data[idx:]


def render_page_views(data: bytes, dpi: int = 100) -> list[list[bytes]]:
    """Per page: full render + detailed upper and lower crops with overlap.

    The small OCR model skips columns in dense regions when given only a
    whole page, so EVERY region needs a dedicated crop — a GOVERNMENT
    WARNING in the bottom third must not depend on the full view alone.
    The full-page view keeps paragraphs that straddle the crop boundary
    intact. Speed comes from the lower DPI + preprocessing (see
    preprocess_for_ocr), not from dropping coverage.
    """
    clean = sanitize_pdf_bytes(data)
    doc = fitz.open(stream=clean, filetype="pdf")
    pages = []
    for page in doc:
        r = page.rect
        split, overlap = r.height * 0.7, r.height * 0.05
        views = [page.get_pixmap(dpi=dpi).tobytes("png")]
        for clip in (fitz.Rect(0, 0, r.width, split + overlap),
                     fitz.Rect(0, split - overlap, r.width, r.height)):
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


def preprocess_for_ocr(image_bytes: bytes, max_side: int = 1400) -> bytes:
    """Lightweight preprocessing for better OCR on small vision models.
    - Grayscale
    - Contrast + sharpen
    - Resize down if needed
    - Output as JPEG (smaller, faster to transmit)
    """
    img = Image.open(io.BytesIO(image_bytes))
    if img.mode != 'L':
        img = img.convert('L')
    # Enhance contrast and sharpness
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(1.6)
    img = img.filter(ImageFilter.SHARPEN)
    # Resize if too large
    if max(img.size) > max_side:
        ratio = max_side / max(img.size)
        new_size = (int(img.width * ratio), int(img.height * ratio))
        img = img.resize(new_size, Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=82)
    return buf.getvalue()
