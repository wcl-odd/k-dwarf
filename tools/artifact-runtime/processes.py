"""Keep commands and raw output even when a child times out or crashes."""

import json
import os
import signal
import subprocess
import threading
from pathlib import Path

from cases import write_json

ROOT = Path(__file__).resolve().parent.parent


class ToolFailure(Exception):
    pass


_children = set()
_children_lock = threading.Lock()


def kill_tree(child):
    """Stop owned descendants even when a nested verifier creates new sessions."""
    pending = [child.pid]
    descendants = []
    while pending:
        pid = pending.pop()
        descendants.append(pid)
        try:
            pending.extend(
                int(p)
                for p in Path(f"/proc/{pid}/task/{pid}/children").read_text().split()
            )
        except (OSError, ValueError):
            pass
    for pid in reversed(descendants):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        os.killpg(child.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def stop_children():
    """Cancel only child process groups launched by this adapter instance."""
    with _children_lock:
        children = list(_children)
    for child in children:
        kill_tree(child)


def execute(command, directory, timeout):
    directory.mkdir(parents=True, exist_ok=True)
    write_json(
        directory / "command.json",
        {
            "argv": [str(x) for x in command],
            "cwd": str(Path.cwd()),
            "timeout": timeout,
            "timeout_scope": "child lifetime",
        },
    )
    try:
        child = subprocess.Popen(
            [str(x) for x in command],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
    except OSError as error:
        write_json(directory / "exit.json", {"launch_error": str(error)})
        raise ToolFailure(str(error)) from error
    with _children_lock:
        _children.add(child)
    try:
        stdout, stderr = child.communicate(timeout=timeout)
        stderr = stderr or ""
    except (subprocess.TimeoutExpired, KeyboardInterrupt) as error:
        # K and compilers spawn children. Stop the whole invocation, not only
        # its Python/JVM parent, and preserve any output already produced.
        kill_tree(child)
        stdout, stderr = child.communicate()
        with _children_lock:
            _children.discard(child)
        stderr = stderr or ""
        (directory / "stdout.txt").write_text(stdout)
        (directory / "stderr.txt").write_text(stderr)
        write_json(
            directory / "exit.json",
            {
                "timeout": isinstance(error, subprocess.TimeoutExpired),
                "interrupted": isinstance(error, KeyboardInterrupt),
            },
        )
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


def read_outcome(text):
    try:
        value = json.loads(text)
    except (ValueError, TypeError) as error:
        raise ToolFailure("malformed backend JSON") from error
    if not isinstance(value, dict):
        raise ToolFailure("backend JSON must be an object")
    return value
