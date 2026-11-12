"""Keep commands and raw output even when a child times out or crashes."""
import json
import os
import signal
import subprocess
import threading
import time
from pathlib import Path

from .input import write_json


class ToolFailure(Exception):
    pass


_children = set()
_children_lock = threading.Lock()


def stop_children():
    """Cancel only child process groups launched by this adapter instance."""
    with _children_lock:
        children = list(_children)
    for child in children:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def execute(command, directory, timeout, *, stdin=None, env=None, merge_stderr=False, cwd=None):
    # Quota waiting is scheduling, not execution of this expression. Reserve a
    # slot before starting its timeout; the child inherits that reservation.
    if len(command) > 1 and Path(str(command[1])).resolve() == Path(__file__).resolve().parents[1] / "run.py":
        import run as dwarf
        queued = time.monotonic()
        with dwarf.frontend_slot():
            return _execute(command, directory, timeout, stdin=stdin,
                            env={**(env or {}), "DWARF_FRONTEND_SLOT_HELD": "1"},
                            merge_stderr=merge_stderr, cwd=cwd, queue_seconds=time.monotonic() - queued)
    return _execute(command, directory, timeout, stdin=stdin, env=env,
                    merge_stderr=merge_stderr, cwd=cwd, queue_seconds=0)


def _execute(command, directory, timeout, *, stdin, env, merge_stderr, cwd, queue_seconds):
    directory.mkdir(parents=True, exist_ok=True)
    write_json(directory / "command.json", {"argv": [str(x) for x in command],
        "cwd": str(Path(cwd).resolve() if cwd else Path.cwd()), "timeout": timeout,
        "environment_overrides": env or {}, "stdin": stdin, "merge_stderr": merge_stderr,
        "queue_seconds": queue_seconds,
        "timeout_scope": "child lifetime after acquiring K frontend quota" if (env or {}).get("DWARF_FRONTEND_SLOT_HELD") == "1" else "child lifetime"})
    try:
        child = subprocess.Popen([str(x) for x in command], stdin=subprocess.PIPE,
             stdout=subprocess.PIPE, stderr=subprocess.STDOUT if merge_stderr else subprocess.PIPE,
             text=True, start_new_session=True,
             cwd=cwd,
             env=None if env is None else dict(os.environ, **env))
    except OSError as error:
        write_json(directory / "exit.json", {"launch_error": str(error)})
        raise ToolFailure(str(error)) from error
    with _children_lock:
        _children.add(child)
    try:
        stdout, stderr = child.communicate(stdin, timeout=timeout)
        stderr = stderr or ""
    except (subprocess.TimeoutExpired, KeyboardInterrupt) as error:
        # K and compilers spawn children. Stop the whole invocation, not only
        # its Python/JVM parent, and preserve any output already produced.
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        stdout, stderr = child.communicate()
        with _children_lock:
            _children.discard(child)
        stderr = stderr or ""
        (directory / "stdout.txt").write_text(stdout)
        (directory / "stderr.txt").write_text(stderr)
        write_json(directory / "exit.json", {"timeout": isinstance(error, subprocess.TimeoutExpired),
                                             "interrupted": isinstance(error, KeyboardInterrupt)})
        if isinstance(error, KeyboardInterrupt):
            raise
        raise ToolFailure(f"timeout after {timeout}s") from error
    process = subprocess.CompletedProcess(command, child.returncode, stdout, stderr)
    with _children_lock:
        _children.discard(child)
    (directory / "stdout.txt").write_text(process.stdout)
    (directory / "stderr.txt").write_text(process.stderr)
    write_json(directory / "exit.json", {"returncode": process.returncode})
    return process


def require_success(process, phase):
    if process.returncode:
        raise ToolFailure(f"{phase}: exit {process.returncode}: {process.stderr[-2000:]}")


def read_payload(text):
    try:
        value = json.loads(text)
    except (ValueError, TypeError) as error:
        raise ToolFailure("malformed backend JSON") from error
    if not isinstance(value, dict):
        raise ToolFailure("backend JSON must be an object")
    return value
