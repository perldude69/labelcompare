"""FastAPI app: list/preview/upload/analyze TTB application PDFs."""
import re
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from server.llm import LlmError, extract_fields, ocr_page
from server.pdf import render_pages, sanitize_pdf_bytes
from server.store import Store
from server.verify import verdict

ROOT = Path(__file__).resolve().parent.parent
APPS_DIR = ROOT / "applications"
WEB_DIR = ROOT / "web"

app = FastAPI(title="LabelCompare")
store = Store(ROOT / "results.json")
progress: dict[str, str] = {}      # filename -> stage text while analyzing
_analyze_lock = threading.Lock()   # one analysis at a time (shared GPU/CPU)


def _safe_path(name: str) -> Path:
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(400, "bad filename")
    path = APPS_DIR / name
    if not path.is_file() or path.suffix.lower() != ".pdf":
        raise HTTPException(404, f"{name} not found")
    return path


def _status_of(name: str, mtime: float) -> tuple[str, bool]:
    if name in progress:
        return "analyzing", False
    cached = store.get(name, mtime)
    if cached is None:
        return "pending", False
    if cached.get("error"):
        return "error", True
    return ("pass" if cached["result"]["passed"] else "fail"), True


@app.get("/api/applications")
def list_applications():
    items = []
    for p in sorted(APPS_DIR.glob("*.pdf")):
        status, has_result = _status_of(p.name, p.stat().st_mtime)
        items.append({"name": p.name, "status": status,
                      "has_result": has_result,
                      "progress": progress.get(p.name)})
    return items


@app.get("/api/applications/{name}/pdf")
def get_pdf(name: str):
    path = _safe_path(name)
    try:
        clean = sanitize_pdf_bytes(path.read_bytes())
    except ValueError as e:
        raise HTTPException(400, str(e))
    return Response(clean, media_type="application/pdf")


@app.get("/api/applications/{name}/result")
def get_result(name: str):
    path = _safe_path(name)
    cached = store.get(name, path.stat().st_mtime)
    if cached is None:
        raise HTTPException(404, "not analyzed yet")
    return cached


@app.post("/api/applications")
def upload(files: list[UploadFile]):
    saved = []
    for f in files:
        base = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(f.filename or "").name)
        if not base.lower().endswith(".pdf"):
            raise HTTPException(400, f"{f.filename}: only .pdf accepted")
        data = f.file.read()
        if data.find(b"%PDF", 0, 1024) == -1:
            raise HTTPException(400, f"{f.filename}: no %PDF header in first 1KB")
        target = APPS_DIR / base
        stem, n = target.stem, 2
        while target.exists():
            target = APPS_DIR / f"{stem}-{n}.pdf"
            n += 1
        target.write_bytes(data)
        saved.append(target.name)
    return {"saved": saved}


@app.post("/api/applications/{name}/analyze")
def analyze(name: str):
    path = _safe_path(name)
    mtime = path.stat().st_mtime
    with _analyze_lock:
        progress[name] = "rendering pages"
        try:
            pages = render_pages(path.read_bytes())
            transcripts = []
            for i, png in enumerate(pages, 1):
                progress[name] = f"OCR page {i}/{len(pages)}"
                transcripts.append(ocr_page(png))
            progress[name] = "extracting fields"
            extraction = extract_fields("\n\n".join(transcripts))
            result = verdict(extraction["application"], extraction["label"])
            entry = {"status": "pass" if result["passed"] else "fail",
                     "result": result, "extraction": extraction,
                     "error": None}
        except (LlmError, ValueError, RuntimeError) as e:
            entry = {"status": "error", "result": None, "extraction": None,
                     "error": str(e)}
        finally:
            progress.pop(name, None)
        store.put(name, mtime, entry)
    return entry


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
