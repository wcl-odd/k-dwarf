"""Small shared file/identity utilities; no collection or native backends."""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
CODE_ROOT = Path(__file__).resolve().parent
RUNNER = CODE_ROOT.parent / 'run.py'
# The standalone entry fixes its own root before importing this package.
ROOT = Path(os.environ.get('DWARF_PROJECT_ROOT', CODE_ROOT.parent)).resolve()
BUILD_COMMAND = 'make' if CODE_ROOT.parent != ROOT else 'make llvm'

@contextmanager
def workspace_lock():
    (ROOT/'build').mkdir(exist_ok=True)
    with (ROOT/'build/verification.lock').open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield
