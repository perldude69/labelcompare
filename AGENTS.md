# LabelCompare — AGENTS.md

## Project structure
```
server/          FastAPI app (port 1776)
  app.py         Routes, pipeline orchestration, analysis lock
  store.py       results.json cache (keyed by filename + mtime)
  pdf.py         PyMuPDF rendering + OCR preprocessing
  llm.py         Clients for llama.cpp servers (GLM-OCR:8090, Qwen:8080)
  verify.py      Deterministic field comparison + health warning check
  postprocess.py Fixes known LLM extraction bugs (marker dup, leakage, backfill)
web/             Static frontend (vanilla JS/CSS/HTML)
tests/           pytest — mocks LLM calls, no llama.cpp servers needed
applications/    PDFs sorted into unprocessed/ validated/ failed/
knowledge/       TTB requirements doc grounded in 27 CFR Parts 4, 5, 7, 16
results.json     Persisted analysis cache (gitignored)
```

## Dependencies
`requirements.txt`: fastapi, uvicorn, pymupdf, python-multipart, httpx, pytest

## Commands
- **Run server**: `uvicorn server.app:app --host 0.0.0.0 --port 1776` (from `.venv`)
- **Run tests**: `pytest` (no special flags needed)
- **Single test file**: `pytest tests/test_verify.py`
- **Single test**: `pytest tests/test_verify.py::test_verdict_pass`
- **Venv**: `python3 -m venv .venv` then `.venv/bin/pip install -r requirements.txt`

## Test quirks
- All LLM-dependent tests use monkeypatch — no external servers needed
- `MINIMAL_PDF` in test_app.py provides valid-looking PDF bytes
- `tmp_path` fixture used for isolated app + store in test_app
- Tests use `FastAPI TestClient`; monkeypatch `appmod.ocr_page`, `appmod.extract_fields`, `appmod.analyze_compliance` to avoid real LLM calls

## Required external services (dev only, not for tests)
Two llama.cpp servers on localhost:
- `127.0.0.1:8090` — GLM-OCR (multimodal model, overridable via `OCR_URL`)
- `127.0.0.1:8080` — Qwen2.5-7B-Instruct (overridable via `QWEN_URL`)

## Key gotchas
- **Analysis is single-threaded**: `_analyze_lock` in app.py prevents concurrent runs (shared GPU)
- **Results invalidate by mtime**: `store.get(name, mtime)` returns `None` if file changed since last analysis
- **Transcript cap preserves both ends**: `cap_transcript()` keeps head + tail with truncation notice in middle — label artwork text is at the tail
- **LLM extraction postprocessing** (`postprocess.py`) fixes three known issues: markers duplicated in both lists, form values leaked into label, missing form brand backfilled
- **Health warning check is case-sensitive**: `verify.check_warning()` enforces exact uppercase on the warning body; only field with case sensitivity
- **PDF upload validation**: looks for `%PDF` within first 1024 bytes; junk prefix (e.g. PHP error HTML) is stripped in `sanitize_pdf_bytes`
- **Name collisions**: filenames must be unique across all three sections; collisions get `-2`, `-3`, etc. suffix
- **Auto-sort on analyze**: unprocessed files move to `validated/` or `failed/` based on the three required field matches (brand, ABV, warning)
- **Progress polling**: UI polls `/api/applications` every 1.5s during analysis to show stage text
- **Error results are cached too**: failed analyses persist so error state survives page refresh

## API surface
See `README.md:87-97` for the full API table. Upload validates PDF magic bytes; `move` only accepts `validated` or `failed` targets; `recycle` clears analysis result and returns to unprocessed.

## Style conventions
- **Imports**: standard lib first, third-party second, local third
- **Separator**: one blank line between imports and code, two blank lines before class/top-level def
- **Docstrings**: present on public modules and functions
- **No TypeScript/Python type annotations on I/O operations**; only used where helpful internally
- **Frontend**: vanilla JS (no frameworks), single `app.js` with `$()` shorthand for `getElementById`
