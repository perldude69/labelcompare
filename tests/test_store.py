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


def test_delete_removes_entry_and_persists(tmp_path):
    p = tmp_path / "results.json"
    s = Store(p)
    s.put("a.pdf", 1.0, {"passed": True})
    s.delete("a.pdf")
    assert s.get("a.pdf", 1.0) is None
    assert Store(p).get("a.pdf", 1.0) is None


def test_delete_missing_is_noop(tmp_path):
    s = Store(tmp_path / "results.json")
    s.delete("nope.pdf")  # must not raise


def test_clear_removes_everything_and_persists(tmp_path):
    p = tmp_path / "results.json"
    s = Store(p)
    s.put("a.pdf", 1.0, {"passed": True})
    s.put("b.pdf", 2.0, {"passed": False})
    s.clear()
    assert s.get("a.pdf", 1.0) is None
    assert Store(p).get("b.pdf", 2.0) is None


def test_rename_rekeys_entry_under_new_name_and_mtime(tmp_path):
    p = tmp_path / "results.json"
    s = Store(p)
    s.put("a.pdf", 1.0, {"passed": True})
    s.rename("a.pdf", "a-2.pdf", 9.0)
    assert s.get("a.pdf", 1.0) is None
    assert s.get("a-2.pdf", 9.0) == {"passed": True}
    assert Store(p).get("a-2.pdf", 9.0) == {"passed": True}


def test_rename_missing_is_noop(tmp_path):
    s = Store(tmp_path / "results.json")
    s.rename("nope.pdf", "new.pdf", 1.0)  # must not raise
    assert s.get("new.pdf", 1.0) is None
