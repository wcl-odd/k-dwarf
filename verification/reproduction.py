"""Run the frozen experiment and check upstream expectations without saved results."""
import argparse
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

from . import cli
from .common import ROOT, BUILD_COMMAND
from .process import ToolFailure, stop_children


def preflight():
    if sys.version_info < (3, 10):
        raise ValueError('Python 3.10 or newer is required')
    if platform.system() != 'Linux' or platform.machine() not in {'x86_64', 'AMD64'}:
        raise ValueError('the validated experiment platform is Linux x86-64')
    programs = {name: shutil.which(name) for name in ('krun', 'kast', 'kparse', 'java')}
    missing = [name for name, path in programs.items() if not path]
    if missing:
        raise ValueError('missing system dependencies: ' + ', '.join(missing) + '; see README.md')
    try:
        version = subprocess.run([programs['krun'], '--version'], capture_output=True,
                                 text=True, timeout=30, cwd=ROOT)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError('could not determine the K version: ' + str(error)) from error
    if version.returncode or 'v7.1.337' not in version.stdout + version.stderr:
        raise ValueError('K v7.1.337 is required; see README.md')
    return {'programs': programs, 'k_version': version.stdout.strip(),
            'k_version_stderr': version.stderr.strip()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='new directory for experiment results')
    parser.add_argument('--definition', type=Path, default=ROOT/'build/llvm-kompiled',
                        help='existing LLVM definition (default: build/llvm-kompiled)')
    parser.add_argument('--source', choices=['all', 'lldb', 'gdb'], default='all')
    parser.add_argument('--timeout', type=cli.positive, default=120)
    parser.add_argument('--depth', type=cli.positive, default=10000)
    parser.add_argument('--jobs', type=cli.positive, choices=range(1, 9), default=4)
    options = parser.parse_args(argv)
    try:
        options.output = Path(os.path.abspath(options.output))
        options.definition = Path(os.path.abspath(options.definition))
        if os.path.lexists(options.output):
            raise ValueError('output must not exist: ' + str(options.output))
        if any(p.is_symlink() for p in options.output.parents):
            raise ValueError('output path cannot follow a symlink')
        for name in ('semantics', 'scripts', 'test-corpus', 'results'):
            if options.output.is_relative_to(ROOT/name):
                raise ValueError('output cannot be inside project inputs')
        if (options.definition.is_relative_to(options.output) or
                options.output.is_relative_to(options.definition)):
            raise ValueError('output and compiled definition must be separate')
        if not (options.definition/'compiled.bin').is_file():
            raise ValueError('compiled K definition missing: ' + str(options.definition) +
                             '; run ' + BUILD_COMMAND + ' or specify --definition')
        options.corpus = ROOT/'test-corpus'
        options.require_complete = False
        # Use the same in-process execution and checking workflow as verify.py.
        # Only the public experiment's completion exit policy differs.
        with cli.execution_environment():
            options.environment = preflight()
            return cli.run(options, experiment=True)
    except KeyboardInterrupt:
        stop_children()
        return 130
    except (OSError, ValueError, KeyError, TypeError, ToolFailure) as error:
        print('reproduce: ' + str(error), file=sys.stderr)
        return 1 if isinstance(error, ToolFailure) else 2


if __name__ == '__main__':
    raise SystemExit(main())
