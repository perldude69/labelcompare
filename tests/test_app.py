import io

import pytest
from fastapi.testclient import TestClient

import server.app as appmod
from server.store import Store

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
    monkeypatch.setattr(appmod, "store", Store(tmp_path / "results.json"))
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
