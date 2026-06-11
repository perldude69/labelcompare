import copy
import io

import pytest
from fastapi.testclient import TestClient

import server.app as appmod
from server.store import Store
from server.verify import STATUTORY_WARNING

MINIMAL_PDF = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 100 100]>>endobj\n"
    b"trailer<</Root 1 0 R>>\n%%EOF\n"
)

PASS_EXTRACTION = {
    "application": {"brand_name": "X", "alcohol_content": "40%"},
    "label": {"brand_name": "X", "alcohol_content": "40%",
              "government_warning": STATUTORY_WARNING.upper()},
}
FAIL_EXTRACTION = {
    "application": {"brand_name": "X", "alcohol_content": "40%"},
    "label": {"brand_name": "X", "alcohol_content": "40%",
              "government_warning": None},
}
COMPLIANCE_STUB = {
    "product_category": "unknown",
    "overall_assessment": "needs_human_review",
    "findings": [],
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    apps_root = tmp_path / "applications"
    monkeypatch.setattr(appmod, "APPS_ROOT", apps_root)
    for attr, sub in (("UNPROCESSED_DIR", "unprocessed"),
                      ("VALIDATED_DIR", "validated"),
                      ("FAILED_DIR", "failed")):
        d = apps_root / sub
        d.mkdir(parents=True)
        monkeypatch.setattr(appmod, attr, d)
    (appmod.UNPROCESSED_DIR / "sample.pdf").write_bytes(MINIMAL_PDF)
    monkeypatch.setattr(appmod, "store", Store(tmp_path / "results.json"))
    appmod.progress.clear()
    return TestClient(appmod.app)


def mock_pipeline(monkeypatch, extraction):
    monkeypatch.setattr(appmod, "ocr_page", lambda png: "BRAND X 40% TEXT")
    monkeypatch.setattr(appmod, "extract_fields",
                        lambda t: copy.deepcopy(extraction))
    monkeypatch.setattr(appmod, "analyze_compliance",
                        lambda *a, **k: dict(COMPLIANCE_STUB))


def names(section_items):
    return [i["name"] for i in section_items]


# ---------- listing ----------

def test_list_applications_has_exactly_three_sections(client):
    r = client.get("/api/applications")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"unprocessed", "validated", "failed"}
    assert names(body["unprocessed"]) == ["sample.pdf"]
    assert body["unprocessed"][0]["status"] == "pending"


# ---------- pdf serving / upload ----------

def test_get_pdf_sanitized(client):
    (appmod.UNPROCESSED_DIR / "dirty.pdf").write_bytes(
        b"<php junk>" + MINIMAL_PDF)
    r = client.get("/api/applications/dirty.pdf/pdf")
    assert r.status_code == 200
    assert r.content.startswith(b"%PDF")


def test_get_pdf_traversal_blocked(client):
    r = client.get("/api/applications/..%2Fresults.json/pdf")
    assert r.status_code in (400, 404)


def test_upload_lands_in_unprocessed(client):
    r = client.post("/api/applications", files=[
        ("files", ("new one.pdf", io.BytesIO(MINIMAL_PDF), "application/pdf"))])
    assert r.status_code == 200
    body = client.get("/api/applications").json()
    assert "new_one.pdf" in names(body["unprocessed"])


def test_upload_rejects_non_pdf(client):
    r = client.post("/api/applications", files=[
        ("files", ("evil.pdf", io.BytesIO(b"MZ not a pdf" * 100),
                   "application/pdf"))])
    assert r.status_code == 400


def test_upload_collision_gets_suffix(client):
    for _ in range(2):
        client.post("/api/applications", files=[
            ("files", ("dup.pdf", io.BytesIO(MINIMAL_PDF), "application/pdf"))])
    unproc = names(client.get("/api/applications").json()["unprocessed"])
    assert "dup.pdf" in unproc and "dup-2.pdf" in unproc


def test_upload_dedupes_across_sections(client):
    """A filename must be unique across ALL sections, otherwise the
    name-keyed lookups hit the wrong file."""
    (appmod.VALIDATED_DIR / "dup.pdf").write_bytes(MINIMAL_PDF)
    r = client.post("/api/applications", files=[
        ("files", ("dup.pdf", io.BytesIO(MINIMAL_PDF), "application/pdf"))])
    assert r.json()["saved"] == ["dup-2.pdf"]


# ---------- analyze ----------

def test_analyze_fail_auto_sorts_to_failed(client, monkeypatch):
    mock_pipeline(monkeypatch, FAIL_EXTRACTION)
    r = client.post("/api/applications/sample.pdf/analyze")
    assert r.status_code == 200
    assert r.json()["status"] == "fail"          # warning missing
    assert r.json()["result"]["passed"] is False
    assert "compliance" in r.json()
    body = client.get("/api/applications").json()
    assert names(body["unprocessed"]) == []
    assert names(body["failed"]) == ["sample.pdf"]
    assert body["failed"][0]["status"] == "fail"
    # result is retrievable after the auto-move
    assert client.get("/api/applications/sample.pdf/result").status_code == 200


def test_analyze_pass_auto_sorts_to_validated(client, monkeypatch):
    mock_pipeline(monkeypatch, PASS_EXTRACTION)
    r = client.post("/api/applications/sample.pdf/analyze")
    assert r.json()["status"] == "pass"
    body = client.get("/api/applications").json()
    assert names(body["validated"]) == ["sample.pdf"]
    assert body["validated"][0]["status"] == "pass"
    assert client.get("/api/applications/sample.pdf/result").status_code == 200


def test_analyze_collision_renames_and_keeps_result(client, monkeypatch):
    """If failed/sample.pdf already exists, the analyzed file must be renamed
    (not left behind) and its result must follow the new name — and the
    pre-existing file must NOT inherit the new file's verdict."""
    (appmod.FAILED_DIR / "sample.pdf").write_bytes(MINIMAL_PDF + b"%other")
    mock_pipeline(monkeypatch, FAIL_EXTRACTION)
    r = client.post("/api/applications/sample.pdf/analyze")
    assert r.status_code == 200
    body = client.get("/api/applications").json()
    assert names(body["unprocessed"]) == []
    assert sorted(names(body["failed"])) == ["sample-2.pdf", "sample.pdf"]
    assert client.get(
        "/api/applications/sample-2.pdf/result").status_code == 200
    # the pre-existing failed/sample.pdf was never analyzed
    assert client.get(
        "/api/applications/sample.pdf/result").status_code == 404


def test_analyze_error_is_persisted(client, monkeypatch):
    from server.llm import LlmError

    def boom(png):
        raise LlmError("OCR server unreachable")

    monkeypatch.setattr(appmod, "ocr_page", boom)
    r = client.post("/api/applications/sample.pdf/analyze")
    assert r.status_code == 200
    assert r.json()["status"] == "error"
    assert "unreachable" in r.json()["error"]
    # the error must survive a refresh: status + result both come from the store
    body = client.get("/api/applications").json()
    assert body["unprocessed"][0]["status"] == "error"
    r2 = client.get("/api/applications/sample.pdf/result")
    assert r2.status_code == 200
    assert r2.json()["status"] == "error"


def test_reanalyze_in_place_from_failed(client, monkeypatch):
    mock_pipeline(monkeypatch, FAIL_EXTRACTION)
    client.post("/api/applications/sample.pdf/analyze")
    # now in failed/ — re-analysis must work and not move the file again
    r = client.post("/api/applications/sample.pdf/analyze")
    assert r.status_code == 200
    body = client.get("/api/applications").json()
    assert names(body["failed"]) == ["sample.pdf"]
    assert client.get("/api/applications/sample.pdf/result").status_code == 200


def test_result_404_when_not_analyzed(client):
    assert client.get("/api/applications/sample.pdf/result").status_code == 404


# ---------- move / recycle / reset ----------

def test_move_preserves_result(client, monkeypatch):
    mock_pipeline(monkeypatch, FAIL_EXTRACTION)
    client.post("/api/applications/sample.pdf/analyze")   # -> failed/
    r = client.post("/api/applications/sample.pdf/move?to=validated")
    assert r.status_code == 200
    body = client.get("/api/applications").json()
    assert names(body["validated"]) == ["sample.pdf"]
    assert names(body["failed"]) == []
    assert client.get("/api/applications/sample.pdf/result").status_code == 200


def test_move_collision_renames_and_rekeys_result(client, monkeypatch):
    mock_pipeline(monkeypatch, FAIL_EXTRACTION)
    client.post("/api/applications/sample.pdf/analyze")   # -> failed/
    (appmod.VALIDATED_DIR / "sample.pdf").write_bytes(MINIMAL_PDF + b"%other")
    r = client.post("/api/applications/sample.pdf/move?to=validated")
    assert r.status_code == 200
    assert r.json()["name"] == "sample-2.pdf"
    assert client.get(
        "/api/applications/sample-2.pdf/result").status_code == 200


def test_move_rejects_bad_target(client):
    r = client.post("/api/applications/sample.pdf/move?to=approved")
    assert r.status_code == 400


def test_recycle_moves_back_and_deletes_result(client, monkeypatch):
    mock_pipeline(monkeypatch, FAIL_EXTRACTION)
    client.post("/api/applications/sample.pdf/analyze")   # -> failed/
    r = client.post("/api/applications/sample.pdf/recycle")
    assert r.status_code == 200
    body = client.get("/api/applications").json()
    assert names(body["unprocessed"]) == ["sample.pdf"]
    assert names(body["failed"]) == []
    assert client.get("/api/applications/sample.pdf/result").status_code == 404


def test_reset_clears_everything(client, monkeypatch):
    mock_pipeline(monkeypatch, FAIL_EXTRACTION)
    client.post("/api/applications/sample.pdf/analyze")
    client.post("/api/applications", files=[
        ("files", ("extra.pdf", io.BytesIO(MINIMAL_PDF), "application/pdf"))])
    r = client.post("/api/reset")
    assert r.status_code == 200
    body = client.get("/api/applications").json()
    assert all(items == [] for items in body.values())
    assert appmod.store.get("sample.pdf", 0) is None


def test_approve_endpoint_removed(client):
    r = client.post("/api/applications/sample.pdf/approve")
    assert r.status_code == 404
