"""Small shared file/identity utilities; no collection or native backends."""
from contextlib import contextmanager
import fcntl
import hashlib
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def fingerprint(path):
    path = Path(path)
    if not path.is_file():
        return {"path": str(path), "exists": False}
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return {"path": str(path.resolve()), "sha256": h.hexdigest(), "size": path.stat().st_size}

@contextmanager
def workspace_lock():
    Path('/tmp/locks').mkdir(exist_ok=True)
    with open('/tmp/locks/kframework.lock', 'a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield
