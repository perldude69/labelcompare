# LabelCompare Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Local web app that lists/uploads TTB application PDFs, previews them, OCRs them with local llama.cpp models, and verifies label fields against application form data (pass = ALL-CAPS government warning + brand match + ABV match).

**Architecture:** FastAPI app on `0.0.0.0:1776` serving a vanilla JS frontend. Pipeline per PDF: PyMuPDF renders pages → GLM-OCR (`127.0.0.1:8090`) transcribes each page → Qwen2.5-7B (`127.0.0.1:8080`) structures the transcript into application-vs-label JSON (grammar-constrained) → pure-Python verification. Results cached in `results.json`.

**Tech Stack:** Python 3.12 venv at `.venv/` (already created: fastapi, uvicorn, pymupdf, python-multipart, httpx, pytest). Frontend: vanilla HTML/JS/CSS, no build step.

**Verified environment facts (do not re-derive):**
- GLM-OCR on :8090 accepts OpenAI `/v1/chat/completions` with `image_url` data-URI PNG; ~17s per 150-DPI page; output preserves case well.
- Qwen on :8080 honors `response_format: {"type":"json_schema", ...}` (grammar-enforced JSON).
- PyMuPDF (`import fitz`) renders all three sample PDFs correctly **after stripping bytes before `%PDF`** (`cies.pdf` has a 158-byte PHP-error prefix; the two scans have broken xrefs that PyMuPDF repairs).
- Run all Python via `.venv/bin/python` / `.venv/bin/pytest` from `/opt/labelcompare`.

---

## File structure

```
server/__init__.py      (empty)
server/pdf.py           sanitize PDF bytes, render pages to PNG
server/verify.py        pure verification logic (warning/brand/ABV/fields)
server/store.py         results.json cache keyed by (filename, mtime)
server/llm.py           httpx clients for GLM-OCR and Qwen (+ prompts, schema)
server/app.py           FastAPI routes, progress tracking, static serving
web/index.html          UI shell
web/style.css           styling
web/app.js              sidebar, preview, analyze/batch/upload, results table
tests/test_pdf.py
tests/test_verify.py
tests/test_store.py
tests/test_app.py       TestClient tests with mocked LLM
requirements.txt
README.md
```

---

### Task 1: Scaffolding

**Files:** Create `requirements.txt`, `server/__init__.py`, `tests/__init__.py`, `pytest.ini`

- [ ] **Step 1: Create files**

`requirements.txt`:
```
fastapi
uvicorn
pymupdf
python-multipart
httpx
pytest
```

`pytest.ini`:
```ini
[pytest]
testpaths = tests
```

`server/__init__.py` and `tests/__init__.py`: empty files.

- [ ] **Step 2: Verify pytest runs**

Run: `.venv/bin/pytest`
Expected: `no tests ran` (exit 5 is fine).

- [ ] **Step 3: Commit**

```bash
git add requirements.txt pytest.ini server/__init__.py tests/__init__.py
git commit -m "[chore] scaffolding: requirements, pytest config, packages"
```

---

### Task 2: PDF sanitizing + rendering (`server/pdf.py`)

**Files:** Create `server/pdf.py`, `tests/test_pdf.py`

- [ ] **Step 1: Write failing tests**

`tests/test_pdf.py`:
```python
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
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `.venv/bin/pytest tests/test_pdf.py -v`
Expected: FAIL / ERROR with `ModuleNotFoundError: No module named 'server.pdf'`

- [ ] **Step 3: Implement**

`server/pdf.py`:
```python
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
```

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/pytest tests/test_pdf.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add server/pdf.py tests/test_pdf.py
git commit -m "[feat] PDF sanitizing (junk prefix) and page rendering"
```

---

### Task 3: Verification logic (`server/verify.py`)

**Files:** Create `server/verify.py`, `tests/test_verify.py`

- [ ] **Step 1: Write failing tests**

`tests/test_verify.py`:
```python
from server.verify import (
    parse_abv, normalize, brands_match, check_warning, verdict,
)

GOOD_WARNING = (
    "GOVERNMENT WARNING: (1) ACCORDING TO THE SURGEON GENERAL, WOMEN "
    "SHOULD NOT DRINK ALCOHOLIC BEVERAGES DURING PREGNANCY BECAUSE OF THE "
    "RISK OF BIRTH DEFECTS. (2) CONSUMPTION OF ALCOHOLIC BEVERAGES IMPAIRS "
    "YOUR ABILITY TO DRIVE A CAR OR OPERATE MACHINERY, AND MAY CAUSE "
    "HEALTH PROBLEMS."
)


def test_parse_abv():
    assert parse_abv("ALC. 12.5% BY VOL") == 12.5
    assert parse_abv("40% ALC/VOL") == 40.0
    assert parse_abv("12.5") == 12.5
    assert parse_abv(None) is None
    assert parse_abv("no number here") is None


def test_normalize():
    assert normalize("  CIES   2013 ") == "cies 2013"
    assert normalize("Smirnoff!") == "smirnoff"


def test_brands_match_case_insensitive():
    assert brands_match("CIES", "Cies")
    assert brands_match("CIES", "CIES 2013 100% ALBARINO")  # containment
    assert not brands_match("CIES", "SMIRNOFF")
    assert not brands_match(None, "CIES")


def test_check_warning_good():
    r = check_warning(GOOD_WARNING)
    assert r["present"] and r["content_ok"] and r["caps_ok"]
    assert r["ok"]


def test_check_warning_lowercase_body_fails_caps():
    bad = GOOD_WARNING.replace("WOMEN", "women")
    r = check_warning(bad)
    assert r["present"] and r["content_ok"] and not r["caps_ok"]
    assert not r["ok"]


def test_check_warning_missing_clause_fails_content():
    bad = GOOD_WARNING[:80]
    r = check_warning(bad)
    assert not r["content_ok"] and not r["ok"]


def test_check_warning_absent():
    r = check_warning(None)
    assert not r["present"] and not r["ok"]


def test_verdict_pass():
    application = {"brand_name": "CIES", "alcohol_content": "12.5%",
                   "class_type": "TABLE WHITE WINE", "net_contents": "750ML",
                   "bottler": "RODRIGO MENDEZ", "country_of_origin": "SPAIN"}
    label = {"brand_name": "Cies 2013", "alcohol_content": "ALC. 12.5% BY VOL.",
             "net_contents": "750ML", "government_warning": GOOD_WARNING}
    v = verdict(application, label)
    assert v["passed"] is True
    assert v["fields"]["brand_name"]["status"] == "match"
    assert v["fields"]["alcohol_content"]["status"] == "match"
    assert v["fields"]["government_warning"]["status"] == "match"


def test_verdict_fail_abv_mismatch():
    v = verdict({"brand_name": "X", "alcohol_content": "40%"},
                {"brand_name": "X", "alcohol_content": "37.5%",
                 "government_warning": GOOD_WARNING})
    assert v["passed"] is False
    assert v["fields"]["alcohol_content"]["status"] == "mismatch"


def test_verdict_missing_required_field():
    v = verdict({"brand_name": "X", "alcohol_content": "40%"},
                {"brand_name": None, "alcohol_content": "40%",
                 "government_warning": GOOD_WARNING})
    assert v["passed"] is False
    assert v["fields"]["brand_name"]["status"] == "missing"
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `.venv/bin/pytest tests/test_verify.py -v`
Expected: ERROR `No module named 'server.verify'`

- [ ] **Step 3: Implement**

`server/verify.py`:
```python
"""Pure verification logic. No I/O, no LLM calls."""
import re

# 27 CFR 16.21 statutory warning text.
STATUTORY_WARNING = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women "
    "should not drink alcoholic beverages during pregnancy because of the "
    "risk of birth defects. (2) Consumption of alcoholic beverages impairs "
    "your ability to drive a car or operate machinery, and may cause "
    "health problems."
)

REQUIRED_FIELDS = ("brand_name", "alcohol_content", "government_warning")
INFO_FIELDS = ("class_type", "net_contents", "bottler", "country_of_origin")


def normalize(s):
    """Lowercase, drop punctuation, collapse whitespace."""
    if s is None:
        return ""
    s = re.sub(r"[^a-z0-9% ]+", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def parse_abv(s):
    """First percentage-like number in the string, else a bare number."""
    if s is None:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", s)
    if not m:
        m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*", s)
    return float(m.group(1)) if m else None


def brands_match(form_brand, label_brand):
    """Case-insensitive; allows containment either way (label often adds
    vintage/varietal around the brand name)."""
    a, b = normalize(form_brand), normalize(label_brand)
    if not a or not b:
        return False
    return a in b or b in a


def check_warning(warning):
    """The only case-sensitive check in the app."""
    result = {"present": False, "content_ok": False, "caps_ok": False,
              "ok": False, "text": warning}
    if not warning or not warning.strip():
        return result
    result["present"] = True
    # Content: compare normalized (case-insensitive) against statutory text.
    result["content_ok"] = normalize(warning) == normalize(STATUTORY_WARNING)
    # Caps: every letter in the warning must be uppercase.
    result["caps_ok"] = warning == warning.upper()
    result["ok"] = result["content_ok"] and result["caps_ok"]
    return result


def _field(form_val, label_val, matched):
    if matched:
        status = "match"
    elif form_val and label_val:
        status = "mismatch"
    else:
        status = "missing"
    return {"application": form_val, "label": label_val, "status": status}


def verdict(application, label):
    """Compare extracted application-form fields against label fields."""
    application = application or {}
    label = label or {}
    fields = {}

    fields["brand_name"] = _field(
        application.get("brand_name"), label.get("brand_name"),
        brands_match(application.get("brand_name"), label.get("brand_name")))

    form_abv = parse_abv(application.get("alcohol_content"))
    label_abv = parse_abv(label.get("alcohol_content"))
    fields["alcohol_content"] = _field(
        application.get("alcohol_content"), label.get("alcohol_content"),
        form_abv is not None and form_abv == label_abv)

    w = check_warning(label.get("government_warning"))
    fields["government_warning"] = {
        "application": "(required by 27 CFR 16.21)",
        "label": label.get("government_warning"),
        "status": "match" if w["ok"] else ("missing" if not w["present"]
                                           else "mismatch"),
        "detail": w,
    }

    # Informational fields: shown in the UI, never affect pass/fail.
    for name in INFO_FIELDS:
        fv, lv = application.get(name), label.get(name)
        if fv and lv:
            matched = normalize(fv) == normalize(lv) or brands_match(fv, lv)
            fields[name] = _field(fv, lv, matched)
        else:
            fields[name] = {"application": fv, "label": lv, "status": "info"}

    passed = all(fields[f]["status"] == "match" for f in REQUIRED_FIELDS)
    return {"passed": passed, "fields": fields}
```

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/pytest tests/test_verify.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add server/verify.py tests/test_verify.py
git commit -m "[feat] verification: warning caps/content, brand, ABV, verdict"
```

---

### Task 4: Results cache (`server/store.py`)

**Files:** Create `server/store.py`, `tests/test_store.py`

- [ ] **Step 1: Write failing tests**

`tests/test_store.py`:
```python
from server.store import Store


def test_roundtrip(tmp_path):
    s = Store(tmp_path / "results.json")
    assert s.get("a.pdf", 111.0) is None
    s.put("a.pdf", 111.0, {"passed": True})
    assert s.get("a.pdf", 111.0) == {"passed": True}


def test_stale_mtime_returns_none(tmp_path):
    s = Store(tmp_path / "results.json")
    s.put("a.pdf", 111.0, {"passed": True})
    assert s.get("a.pdf", 222.0) is None


def test_persists_across_instances(tmp_path):
    p = tmp_path / "results.json"
    Store(p).put("a.pdf", 1.0, {"passed": False})
    assert Store(p).get("a.pdf", 1.0) == {"passed": False}
```

- [ ] **Step 2: Run tests, verify fail**

Run: `.venv/bin/pytest tests/test_store.py -v`
Expected: ERROR `No module named 'server.store'`

- [ ] **Step 3: Implement**

`server/store.py`:
```python
"""Result cache persisted to results.json, keyed by filename + mtime."""
import json
import threading
from pathlib import Path


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._data = {}
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text())
            except (json.JSONDecodeError, OSError):
                self._data = {}

    def get(self, name, mtime):
        entry = self._data.get(name)
        if entry and entry["mtime"] == mtime:
            return entry["result"]
        return None

    def put(self, name, mtime, result):
        with self._lock:
            self._data[name] = {"mtime": mtime, "result": result}
            self.path.write_text(json.dumps(self._data, indent=2))
```

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/pytest tests/test_store.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add server/store.py tests/test_store.py
git commit -m "[feat] results cache keyed by filename and mtime"
```

---

### Task 5: LLM clients (`server/llm.py`)

No unit tests for HTTP calls (verified live in Task 8); JSON-parsing helper is unit-tested.

**Files:** Create `server/llm.py`, append to `tests/test_verify.py` — no; create `tests/test_llm.py`

- [ ] **Step 1: Write failing test for the response-parsing helper**

`tests/test_llm.py`:
```python
import pytest
from server.llm import parse_extraction, LlmError


def test_parse_extraction_valid():
    content = '{"application": {"brand_name": "X"}, "label": {"brand_name": "Y"}}'
    out = parse_extraction(content)
    assert out["application"]["brand_name"] == "X"


def test_parse_extraction_invalid_json():
    with pytest.raises(LlmError):
        parse_extraction("not json {")


def test_parse_extraction_missing_keys():
    with pytest.raises(LlmError):
        parse_extraction('{"foo": 1}')
```

- [ ] **Step 2: Run, verify fail**

Run: `.venv/bin/pytest tests/test_llm.py -v`
Expected: ERROR `No module named 'server.llm'`

- [ ] **Step 3: Implement**

`server/llm.py`:
```python
"""Clients for the local llama.cpp servers."""
import base64
import json
import os

import httpx

OCR_URL = os.environ.get("OCR_URL", "http://127.0.0.1:8090/v1/chat/completions")
QWEN_URL = os.environ.get("QWEN_URL", "http://127.0.0.1:8080/v1/chat/completions")
OCR_TIMEOUT = 240
QWEN_TIMEOUT = 180

OCR_PROMPT = (
    "Transcribe all text in this image exactly as printed. Preserve "
    "capitalization and punctuation. Output only the transcribed text."
)

EXTRACT_PROMPT = """\
The text below is an OCR transcript of a TTB COLA alcohol label application. \
It contains APPLICATION FORM data (typed form fields such as brand name, \
class/type, alcohol content, net contents, bottler name/address, country of \
origin) and, usually after a phrase like "AFFIX COMPLETE SET OF LABELS", the \
text printed on the LABEL itself.

Extract two groups:
- "application": values from the form fields.
- "label": values exactly as printed on the label artwork, preserving the \
exact capitalization from the transcript. For "government_warning", copy the \
full warning verbatim starting at "GOVERNMENT WARNING" through the end of \
the sentence about health problems; preserve every character's case exactly.

Use null for anything not present.

TRANSCRIPT:
{transcript}
"""

EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "application": {
            "type": "object",
            "properties": {
                "brand_name": {"type": ["string", "null"]},
                "class_type": {"type": ["string", "null"]},
                "alcohol_content": {"type": ["string", "null"]},
                "net_contents": {"type": ["string", "null"]},
                "bottler": {"type": ["string", "null"]},
                "country_of_origin": {"type": ["string", "null"]},
            },
            "required": ["brand_name", "class_type", "alcohol_content",
                          "net_contents", "bottler", "country_of_origin"],
        },
        "label": {
            "type": "object",
            "properties": {
                "brand_name": {"type": ["string", "null"]},
                "class_type": {"type": ["string", "null"]},
                "alcohol_content": {"type": ["string", "null"]},
                "net_contents": {"type": ["string", "null"]},
                "bottler": {"type": ["string", "null"]},
                "country_of_origin": {"type": ["string", "null"]},
                "government_warning": {"type": ["string", "null"]},
            },
            "required": ["brand_name", "class_type", "alcohol_content",
                          "net_contents", "bottler", "country_of_origin",
                          "government_warning"],
        },
    },
    "required": ["application", "label"],
}


class LlmError(Exception):
    pass


def parse_extraction(content):
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise LlmError(f"extraction returned invalid JSON: {e}") from e
    if "application" not in data or "label" not in data:
        raise LlmError("extraction JSON missing application/label keys")
    return data


def _post(url, payload, timeout, what):
    try:
        r = httpx.post(url, json=payload, timeout=timeout)
    except httpx.HTTPError as e:
        raise LlmError(f"{what} server unreachable at {url}: {e}") from e
    if r.status_code != 200:
        raise LlmError(f"{what} server error {r.status_code}: {r.text[:200]}")
    return r.json()["choices"][0]["message"]["content"]


def ocr_page(png_bytes):
    b64 = base64.b64encode(png_bytes).decode()
    payload = {
        "model": "glm-ocr",
        "temperature": 0,
        "max_tokens": 3000,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": OCR_PROMPT},
            {"type": "image_url",
             "image_url": {"url": "data:image/png;base64," + b64}},
        ]}],
    }
    return _post(OCR_URL, payload, OCR_TIMEOUT, "OCR")


def extract_fields(transcript):
    payload = {
        "model": "qwen",
        "temperature": 0,
        "max_tokens": 1200,
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": "extract",
                                            "schema": EXTRACTION_SCHEMA}},
        "messages": [{"role": "user",
                      "content": EXTRACT_PROMPT.format(transcript=transcript)}],
    }
    return parse_extraction(_post(QWEN_URL, payload, QWEN_TIMEOUT, "extraction"))
```

- [ ] **Step 4: Run, verify pass**

Run: `.venv/bin/pytest tests/test_llm.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add server/llm.py tests/test_llm.py
git commit -m "[feat] llama.cpp clients: GLM-OCR pages, Qwen schema extraction"
```

---

### Task 6: FastAPI app (`server/app.py`)

**Files:** Create `server/app.py`, `tests/test_app.py`

- [ ] **Step 1: Write failing tests (LLM mocked)**

`tests/test_app.py`:
```python
import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server.app as appmod

MINIMAL_PDF = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 100 100]>>endobj\n"
    b"trailer<</Root 1 0 R>>\n%%EOF\n"
)


@pytest.fixture
def client(tmp_path, monkeypatch):
    apps = tmp_path / "applications"
    apps.mkdir()
    (apps / "sample.pdf").write_bytes(MINIMAL_PDF)
    monkeypatch.setattr(appmod, "APPS_DIR", apps)
    monkeypatch.setattr(appmod, "store",
                        appmod.Store(tmp_path / "results.json"))
    appmod.progress.clear()
    return TestClient(appmod.app)


def test_list_applications(client):
    r = client.get("/api/applications")
    assert r.status_code == 200
    items = r.json()
    assert items[0]["name"] == "sample.pdf"
    assert items[0]["status"] == "pending"


def test_get_pdf_sanitized(client, tmp_path):
    dirty = b"<php junk>" + MINIMAL_PDF
    (tmp_path / "applications" / "dirty.pdf").write_bytes(dirty)
    r = client.get("/api/applications/dirty.pdf/pdf")
    assert r.status_code == 200
    assert r.content.startswith(b"%PDF")


def test_get_pdf_traversal_blocked(client):
    r = client.get("/api/applications/..%2Fresults.json/pdf")
    assert r.status_code in (400, 404)


def test_upload_pdf(client):
    r = client.post("/api/applications", files=[
        ("files", ("new one.pdf", io.BytesIO(MINIMAL_PDF), "application/pdf"))])
    assert r.status_code == 200
    names = [i["name"] for i in client.get("/api/applications").json()]
    assert "new_one.pdf" in names


def test_upload_rejects_non_pdf(client):
    r = client.post("/api/applications", files=[
        ("files", ("evil.pdf", io.BytesIO(b"MZ not a pdf" * 100),
                   "application/pdf"))])
    assert r.status_code == 400


def test_upload_collision_gets_suffix(client):
    for _ in range(2):
        client.post("/api/applications", files=[
            ("files", ("dup.pdf", io.BytesIO(MINIMAL_PDF), "application/pdf"))])
    names = [i["name"] for i in client.get("/api/applications").json()]
    assert "dup.pdf" in names and "dup-2.pdf" in names


def test_analyze_uses_mocked_pipeline(client, monkeypatch):
    monkeypatch.setattr(appmod, "ocr_page", lambda png: "BRAND X 40% TEXT")
    monkeypatch.setattr(appmod, "extract_fields", lambda t: {
        "application": {"brand_name": "X", "alcohol_content": "40%"},
        "label": {"brand_name": "X", "alcohol_content": "40%",
                  "government_warning": None},
    })
    r = client.post("/api/applications/sample.pdf/analyze")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "fail"          # warning missing
    assert body["result"]["passed"] is False
    # cached now
    r2 = client.get("/api/applications/sample.pdf/result")
    assert r2.status_code == 200
    assert client.get("/api/applications").json()[0]["status"] == "fail"


def test_result_404_when_not_analyzed(client):
    assert client.get("/api/applications/sample.pdf/result").status_code == 404


def test_analyze_llm_error_reports_error_status(client, monkeypatch):
    from server.llm import LlmError
    def boom(png):
        raise LlmError("OCR server unreachable")
    monkeypatch.setattr(appmod, "ocr_page", boom)
    r = client.post("/api/applications/sample.pdf/analyze")
    assert r.status_code == 200
    assert r.json()["status"] == "error"
    assert "unreachable" in r.json()["error"]
```

- [ ] **Step 2: Run, verify fail**

Run: `.venv/bin/pytest tests/test_app.py -v`
Expected: ERROR `No module named 'server.app'`

- [ ] **Step 3: Implement**

`server/app.py`:
```python
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
```

Note: `analyze` is a sync `def` route — FastAPI runs it in a threadpool, so
`GET /api/applications` (progress polling) stays responsive during analysis.
`WEB_DIR` must exist before the module imports (`app.mount` checks) — Task 7
creates it; for this task create the empty dir and a stub `web/index.html`
containing `<!doctype html><title>LabelCompare</title>`.

- [ ] **Step 4: Run, verify pass**

Run: `.venv/bin/pytest tests/test_app.py -v`
Expected: 9 passed
Also run full suite: `.venv/bin/pytest` → all pass.

- [ ] **Step 5: Commit**

```bash
git add server/app.py tests/test_app.py web/index.html
git commit -m "[feat] FastAPI API: list, preview, upload, analyze, results"
```

---

### Task 7: Frontend (`web/`)

**Files:** Create/replace `web/index.html`, `web/style.css`, `web/app.js`

No unit tests (vanilla JS, no build); verified end-to-end in Task 8.

- [ ] **Step 1: `web/index.html`**

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LabelCompare — TTB Label Verification</title>
<link rel="stylesheet" href="/static/style.css">
</head>
<body>
<header>
  <h1>LabelCompare</h1>
  <span class="subtitle">TTB label verification prototype</span>
  <div class="actions">
    <button id="analyzeBtn" disabled>Analyze</button>
    <button id="batchBtn">Batch Analyze</button>
    <button id="uploadBtn">Upload PDF</button>
    <input type="file" id="fileInput" accept=".pdf" multiple hidden>
  </div>
</header>
<main>
  <aside id="sidebar" aria-label="Applications">
    <ul id="pdfList"></ul>
    <p class="drophint">Drag &amp; drop PDFs here to upload</p>
  </aside>
  <section id="preview">
    <iframe id="pdfFrame" title="PDF preview"></iframe>
  </section>
  <section id="results">
    <h2>Results</h2>
    <div id="resultBody"><p class="muted">Select a PDF and click Analyze.</p></div>
  </section>
</main>
<script src="/static/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: `web/style.css`**

```css
* { box-sizing: border-box; }
body { margin: 0; font: 14px/1.45 system-ui, sans-serif; color: #1a2233;
       background: #f4f6f9; height: 100vh; display: flex; flex-direction: column; }
header { display: flex; align-items: center; gap: 12px; padding: 10px 16px;
         background: #15355e; color: #fff; }
header h1 { font-size: 18px; margin: 0; }
.subtitle { opacity: .7; font-size: 12px; }
.actions { margin-left: auto; display: flex; gap: 8px; }
button { padding: 7px 14px; border: 0; border-radius: 6px; cursor: pointer;
         background: #2e6fd0; color: #fff; font-weight: 600; }
button:disabled { background: #8aa3c4; cursor: not-allowed; }
main { flex: 1; display: grid; grid-template-columns: 240px 1fr 380px;
       min-height: 0; }
#sidebar { background: #fff; border-right: 1px solid #dde3ec; overflow-y: auto;
           display: flex; flex-direction: column; }
#sidebar.dragover { outline: 2px dashed #2e6fd0; outline-offset: -6px; }
#pdfList { list-style: none; margin: 0; padding: 6px; flex: 1; }
#pdfList li { display: flex; align-items: center; gap: 8px; padding: 8px 10px;
              border-radius: 6px; cursor: pointer; word-break: break-all; }
#pdfList li:hover { background: #eef3fa; }
#pdfList li.selected { background: #dbe7f8; font-weight: 600; }
.badge { width: 18px; height: 18px; flex: none; border-radius: 50%;
         display: inline-flex; align-items: center; justify-content: center;
         font-size: 12px; color: #fff; background: #b9c2d0; }
.badge.pass { background: #1d8a4a; }
.badge.fail { background: #cc3333; }
.badge.error { background: #d9930d; }
.badge.analyzing { background: #2e6fd0; animation: pulse 1s infinite alternate; }
@keyframes pulse { from { opacity: .4; } to { opacity: 1; } }
.prog { font-size: 11px; color: #5a6b85; margin-left: auto; }
.drophint { font-size: 11px; color: #93a1b8; text-align: center; padding: 8px; }
#preview { min-width: 0; }
#pdfFrame { width: 100%; height: 100%; border: 0; background: #5a6470; }
#results { background: #fff; border-left: 1px solid #dde3ec; overflow-y: auto;
           padding: 14px; }
#results h2 { margin: 0 0 10px; font-size: 15px; }
.muted { color: #93a1b8; }
.verdict { padding: 10px 12px; border-radius: 8px; font-weight: 700;
           margin-bottom: 12px; }
.verdict.pass { background: #e2f4e9; color: #156238; }
.verdict.fail { background: #fae4e4; color: #8f1f1f; }
.verdict.error { background: #fdf1d8; color: #7a5408; }
table.fields { width: 100%; border-collapse: collapse; font-size: 13px; }
table.fields th, table.fields td { text-align: left; padding: 6px 8px;
       border-bottom: 1px solid #eef1f6; vertical-align: top; }
tr.match  td.status { color: #1d8a4a; font-weight: 700; }
tr.mismatch { background: #fdeaea; }
tr.mismatch td.status { color: #cc3333; font-weight: 700; }
tr.missing { background: #fdf4dd; }
tr.missing td.status { color: #9a6b00; font-weight: 700; }
tr.info td.status { color: #93a1b8; }
.warningbox { margin-top: 12px; padding: 10px; border-radius: 8px;
              background: #f4f6f9; font-size: 12px; white-space: pre-wrap; }
.warningbox .ok { color: #1d8a4a; }
.warningbox .bad { color: #cc3333; }
```

- [ ] **Step 3: `web/app.js`**

```javascript
const $ = (id) => document.getElementById(id);
let selected = null;
let apps = [];

const FIELD_LABELS = {
  brand_name: "Brand name",
  alcohol_content: "Alcohol content",
  government_warning: "Gov. warning",
  class_type: "Class / type",
  net_contents: "Net contents",
  bottler: "Bottler",
  country_of_origin: "Country of origin",
};
const BADGE = { pass: "✓", fail: "✗", error: "!", analyzing: "⋯",
                pending: "" };

async function refresh() {
  apps = await (await fetch("/api/applications")).json();
  const ul = $("pdfList");
  ul.innerHTML = "";
  for (const a of apps) {
    const li = document.createElement("li");
    li.className = a.name === selected ? "selected" : "";
    const badge = `<span class="badge ${a.status}">${BADGE[a.status] ?? ""}</span>`;
    const prog = a.progress ? `<span class="prog">${a.progress}</span>` : "";
    li.innerHTML = `${badge}<span>${a.name}</span>${prog}`;
    li.onclick = () => select(a.name);
    ul.appendChild(li);
  }
  $("analyzeBtn").disabled = !selected ||
    apps.find((a) => a.name === selected)?.status === "analyzing";
}

async function select(name) {
  selected = name;
  $("pdfFrame").src = `/api/applications/${encodeURIComponent(name)}/pdf`;
  await refresh();
  await showResult(name);
}

async function showResult(name) {
  const body = $("resultBody");
  const r = await fetch(`/api/applications/${encodeURIComponent(name)}/result`);
  if (!r.ok) {
    body.innerHTML = '<p class="muted">Not analyzed yet.</p>';
    return;
  }
  const entry = await r.json();
  if (entry.status === "error") {
    body.innerHTML = `<div class="verdict error">Analysis error</div>
                      <p>${entry.error}</p>`;
    return;
  }
  const v = entry.result;
  let html = `<div class="verdict ${entry.status}">
      ${entry.status === "pass" ? "✓ PASSES minimum requirements"
                                 : "✗ FAILS minimum requirements"}</div>
    <table class="fields"><tr><th>Field</th><th>Application</th>
    <th>Label</th><th></th></tr>`;
  for (const [key, label] of Object.entries(FIELD_LABELS)) {
    const f = v.fields[key];
    if (!f) continue;
    const lab = key === "government_warning"
      ? (f.label ? "(see below)" : "—") : (f.label ?? "—");
    html += `<tr class="${f.status}"><td>${label}</td>
      <td>${f.application ?? "—"}</td><td>${lab}</td>
      <td class="status">${f.status}</td></tr>`;
  }
  html += "</table>";
  const w = v.fields.government_warning?.detail;
  if (w) {
    const yn = (ok, txt) =>
      `<span class="${ok ? "ok" : "bad"}">${ok ? "✓" : "✗"} ${txt}</span>`;
    html += `<div class="warningbox"><b>Government warning</b><br>
      ${yn(w.present, "present")} &nbsp; ${yn(w.content_ok, "statutory text")}
      &nbsp; ${yn(w.caps_ok, "ALL CAPS")}<br><br>${w.text ?? "(not found)"}</div>`;
  }
  body.innerHTML = html;
}

async function analyzeOne(name) {
  const poll = setInterval(refresh, 1500);
  try {
    await fetch(`/api/applications/${encodeURIComponent(name)}/analyze`,
                { method: "POST" });
  } finally {
    clearInterval(poll);
    await refresh();
    if (selected === name) await showResult(name);
  }
}

$("analyzeBtn").onclick = () => selected && analyzeOne(selected);

$("batchBtn").onclick = async () => {
  $("batchBtn").disabled = true;
  try {
    for (const a of [...apps]) await analyzeOne(a.name);
  } finally {
    $("batchBtn").disabled = false;
  }
};

$("uploadBtn").onclick = () => $("fileInput").click();
$("fileInput").onchange = () => uploadFiles($("fileInput").files);

async function uploadFiles(files) {
  if (!files.length) return;
  const fd = new FormData();
  for (const f of files) fd.append("files", f);
  const r = await fetch("/api/applications", { method: "POST", body: fd });
  if (!r.ok) alert(`Upload failed: ${(await r.json()).detail ?? r.status}`);
  await refresh();
}

const sb = $("sidebar");
sb.ondragover = (e) => { e.preventDefault(); sb.classList.add("dragover"); };
sb.ondragleave = () => sb.classList.remove("dragover");
sb.ondrop = (e) => {
  e.preventDefault();
  sb.classList.remove("dragover");
  uploadFiles(e.dataTransfer.files);
};

refresh();
```

- [ ] **Step 4: Commit**

```bash
git add web/
git commit -m "[feat] frontend: sidebar, preview, analyze/batch/upload, results"
```

---

### Task 8: End-to-end verification on the real samples

- [ ] **Step 1: Start the server**

```bash
.venv/bin/uvicorn server.app:app --host 0.0.0.0 --port 1776
```
(run in background)

- [ ] **Step 2: API smoke checks**

```bash
curl -s http://127.0.0.1:1776/api/applications   # 3 PDFs, status pending
curl -s -o /dev/null -w "%{http_code} %{content_type}\n" \
  http://127.0.0.1:1776/api/applications/cies.pdf/pdf   # 200 application/pdf
```

- [ ] **Step 3: Analyze each sample, inspect results**

```bash
for f in cies.pdf ABCWine-scan.pdf smirnoff-scan.pdf; do
  curl -s -X POST "http://127.0.0.1:1776/api/applications/$f/analyze" | head -c 2000
done
```
Expected: each returns `status` of `pass` or `fail` (not `error`) with a
populated `result.fields` and `extraction`. Inspect the extractions against
the actual PDFs; tune `OCR_PROMPT`/`EXTRACT_PROMPT` in `server/llm.py` if
fields are systematically wrong (re-run tests after any change).

- [ ] **Step 4: Browser check (Playwright)**

Open `http://127.0.0.1:1776/`, verify: list renders with status badges,
selecting shows the PDF preview, results panel shows the cached verdicts,
upload of a copy of `cies.pdf` appears as `cies-2.pdf` pending.

- [ ] **Step 5: Commit any tuning, note results**

```bash
git add -A && git commit -m "[fix] prompt/verification tuning from e2e run"
```

---

### Task 9: README

- [ ] **Step 1: Write `README.md`**

Cover: what it does (one paragraph), architecture diagram (ascii), the
verification rules (pass = ALL-CAPS statutory warning + brand match +
ABV match; brand/other fields case-insensitive), how to run
(`.venv/bin/uvicorn server.app:app --host 0.0.0.0 --port 1776`), the
llama.cpp server expectations (ports 8090/8080, overridable via `OCR_URL` /
`QWEN_URL` env vars), API reference table, and known limitations
(sequential batch, ~20-60s per document on local models, prototype security
posture: no auth, LAN exposure by design).

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "[docs] README: usage, architecture, verification rules"
```
