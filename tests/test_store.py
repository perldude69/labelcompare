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
