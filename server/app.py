"""FastAPI app: list/preview/upload/analyze TTB application PDFs."""
import re
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from server.llm import LlmError, analyze_compliance, extract_fields, ocr_page
from server.pdf import preprocess_for_ocr, render_page_views, sanitize_pdf_bytes
from server.postprocess import postprocess_extraction
from server.store import Store
from server.verify import verdict

ROOT = Path(__file__).resolve().parent.parent
APPS_ROOT = ROOT / "applications"
UNPROCESSED_DIR = APPS_ROOT / "unprocessed"
VALIDATED_DIR = APPS_ROOT / "validated"   # the "Passed" section
FAILED_DIR = APPS_ROOT / "failed"
WEB_DIR = ROOT / "web"

app = FastAPI(title="LabelCompare")
store = Store(ROOT / "results.json")
progress: dict[str, str] = {}      # filename -> stage text while analyzing
_analyze_lock = threading.Lock()   # one analysis at a time (shared GPU/CPU)


def _section_dirs() -> tuple[Path, ...]:
    return (UNPROCESSED_DIR, VALIDATED_DIR, FAILED_DIR)


def _ensure_dirs():
    for d in _section_dirs():
        d.mkdir(parents=True, exist_ok=True)
    # Migrate legacy layouts: PDFs in the root -> unprocessed; the retired
    # "approved" section -> validated (approved files had passed).
    migrations = [(APPS_ROOT, UNPROCESSED_DIR),
                  (APPS_ROOT / "approved", VALIDATED_DIR)]
    for src, dest_dir in migrations:
        for p in src.glob("*.pdf"):
            dest = dest_dir / p.name
            if not dest.exists():
                p.rename(dest)
    legacy_approved = APPS_ROOT / "approved"
    if legacy_approved.is_dir() and not any(legacy_approved.iterdir()):
        legacy_approved.rmdir()


_ensure_dirs()


def _resolve_pdf(name: str, skip_dir: Path | None = None) -> Path:
    """Find the PDF by name across sections. Duplicate names across sections
    only occur in legacy/hand-edited layouts; `skip_dir` lets a move prefer
    the copy that is not already in its target section."""
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(400, "bad filename")
    candidates = [base / name for base in _section_dirs()
                  if (base / name).is_file()
                  and (base / name).suffix.lower() == ".pdf"]
    if not candidates:
        raise HTTPException(404, f"{name} not found")
    return next((p for p in candidates if p.parent != skip_dir),
                candidates[0])


def _unique_target(target_dir: Path, name: str, source: Path | None = None) -> Path:
    """Collision-free destination. Names must be unique across ALL sections
    (lookups are name-keyed), so check every section dir — ignoring the
    source file itself when this is a move."""
    def taken(candidate_name: str) -> bool:
        return any((d / candidate_name).exists() and (d / candidate_name) != source
                   for d in _section_dirs())

    target = target_dir / name
    stem, n = target.stem, 2
    while taken(target.name):
        target = target_dir / f"{stem}-{n}.pdf"
        n += 1
    return target


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
    def _list_dir(d: Path):
        items = []
        for p in sorted(d.glob("*.pdf")):
            status, has_result = _status_of(p.name, p.stat().st_mtime)
            items.append({"name": p.name, "status": status,
                          "has_result": has_result,
                          "progress": progress.get(p.name)})
        return items

    return {
        "unprocessed": _list_dir(UNPROCESSED_DIR),
        "validated": _list_dir(VALIDATED_DIR),
        "failed": _list_dir(FAILED_DIR),
    }


@app.post("/api/applications/{name}/move")
def move_pdf(name: str, to: str = "validated"):
    """Manually move a PDF between the Passed (validated) / Failed sections."""
    if to == "validated":
        target_dir = VALIDATED_DIR
    elif to == "failed":
        target_dir = FAILED_DIR
    else:
        raise HTTPException(400, "to must be 'validated' or 'failed'")

    path = _resolve_pdf(name, skip_dir=target_dir)
    if path.parent == target_dir:
        return {"moved": False, "name": path.name, "section": to}

    target = _unique_target(target_dir, path.name, source=path)
    path.rename(target)
    store.rename(name, target.name, target.stat().st_mtime)
    return {"moved": True, "name": target.name, "section": to}


@app.post("/api/applications/{name}/recycle")
def recycle_pdf(name: str):
    """Move PDF back to unprocessed and delete its analysis result."""
    path = _resolve_pdf(name)
    if path.parent != UNPROCESSED_DIR:
        target = _unique_target(UNPROCESSED_DIR, path.name, source=path)
        path.rename(target)
        name_after = target.name
    else:
        name_after = path.name
    store.delete(name)
    return {"recycled": True, "name": name_after, "to": "unprocessed"}


@app.post("/api/reset")
def reset_app():
    """Delete all PDFs from all sections and clear all analysis results."""
    deleted = 0
    for d in _section_dirs():
        for pdf in list(d.glob("*.pdf")):
            pdf.unlink(missing_ok=True)
            deleted += 1
    store.clear()
    progress.clear()
    return {"reset": True, "pdfs_deleted": deleted}


@app.get("/api/applications/{name}/pdf")
def get_pdf(name: str):
    path = _resolve_pdf(name)
    try:
        clean = sanitize_pdf_bytes(path.read_bytes())
    except ValueError as e:
        raise HTTPException(400, str(e))
    return Response(clean, media_type="application/pdf")


@app.get("/api/applications/{name}/result")
def get_result(name: str):
    path = _resolve_pdf(name)
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
        target = _unique_target(UNPROCESSED_DIR, base)
        target.write_bytes(data)
        saved.append(target.name)
    return {"saved": saved}


@app.post("/api/applications/{name}/analyze")
def analyze(name: str):
    path = _resolve_pdf(name)
    mtime = path.stat().st_mtime
    with _analyze_lock:
        progress[name] = "rendering pages"
        try:
            pages = render_page_views(path.read_bytes())
            transcripts = []
            for i, views in enumerate(pages, 1):
                for j, png in enumerate(views, 1):
                    progress[name] = (f"OCR page {i}/{len(pages)} "
                                      f"(view {j}/{len(views)})")
                    txt = ocr_page(preprocess_for_ocr(png))
                    transcripts.append(f"=== PAGE {i} VIEW {j} ===\n{txt}")

            joined_transcript = "\n\n".join(transcripts)

            progress[name] = "extracting fields"
            extraction = extract_fields(joined_transcript)
            postprocess_extraction(extraction, transcripts, joined_transcript)

            result = verdict(extraction.get("application"),
                             extraction.get("label"))

            progress[name] = "analyzing compliance with TTB requirements"
            compliance = analyze_compliance(
                joined_transcript,
                form_data=extraction.get("application"),
            )

            entry = {
                "status": "pass" if result.get("passed") else "fail",
                "result": result,
                "extraction": extraction,
                "compliance": compliance,
                "transcripts": transcripts,  # raw OCR evidence for transparency
                "error": None,
            }
            store.put(name, mtime, entry)

            # Auto-sort unprocessed files into Passed (validated) / Failed.
            # Persisted above first, then re-keyed after the move so a rename
            # failure can never lose the analysis.
            if path.parent == UNPROCESSED_DIR:
                target_dir = VALIDATED_DIR if result.get("passed") else FAILED_DIR
                target = _unique_target(target_dir, path.name, source=path)
                path.rename(target)
                store.rename(name, target.name, target.stat().st_mtime)
        except (LlmError, ValueError, RuntimeError) as e:
            entry = {
                "status": "error",
                "result": None,
                "extraction": None,
                "compliance": None,
                "transcripts": None,
                "error": str(e),
            }
            store.put(name, mtime, entry)  # errors must survive a refresh too
        finally:
            progress.pop(name, None)
    return entry


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
