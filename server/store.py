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
