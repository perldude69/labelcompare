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

    def _save(self):
        self.path.write_text(json.dumps(self._data, indent=2))

    def get(self, name, mtime):
        entry = self._data.get(name)
        if entry and entry["mtime"] == mtime:
            return entry["result"]
        return None

    def put(self, name, mtime, result):
        with self._lock:
            self._data[name] = {"mtime": mtime, "result": result}
            self._save()

    def delete(self, name):
        with self._lock:
            if self._data.pop(name, None) is not None:
                self._save()

    def clear(self):
        with self._lock:
            self._data = {}
            self._save()

    def rename(self, old, new, mtime):
        """Re-key an entry after its file was renamed/moved on disk."""
        with self._lock:
            entry = self._data.pop(old, None)
            if entry is None:
                return
            self._data[new] = {"mtime": mtime, "result": entry["result"]}
            self._save()
