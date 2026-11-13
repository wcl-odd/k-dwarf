# System requirements and installation

## Validated environment

- Linux x86-64; the recorded installation is Ubuntu 22.04.5 LTS.
- Python 3.10 or newer; no third-party Python packages.
- K Framework **v7.1.337**, including the LLVM backend and `kompile`, `kast`, `krun` on PATH.
- Java 21 (the validated run uses OpenJDK 21); use the Java version required by the selected K distribution.
- LLVM/Clang **15.0.7** is the validated K compiler toolchain. The compiler used by K must match its distribution, not a separately installed debugger's LLVM release.
- GNU make, a C/C++ toolchain, CMake, pkg-config and util-linux (`flock`).
- Native development libraries required by K's LLVM distribution: GMP, MPFR, Boost, libffi, libfmt, jemalloc, libunwind, Z3 and zlib. Follow that distribution's package versions.

K releases and installation instructions: <https://github.com/runtimeverification/k/releases/tag/v7.1.337> and <https://kframework.org/docs/getting-started/>. Install the matching Linux distribution and its native dependencies; preserve its supported compiler/library setup. Do not copy machine-specific wrapper scripts or absolute library paths from another installation.

On Ubuntu, obtain the general build prerequisites with your package manager, for example:

```bash
sudo apt-get update
sudo apt-get install build-essential make cmake pkg-config util-linux \
  clang-15 llvm-15-dev lld-15 libgmp-dev libmpfr-dev libboost-dev \
  libffi-dev libfmt-dev libjemalloc-dev libunwind-dev libz3-dev zlib1g-dev
```

Install Java 21 through your OS/JDK provider and install K v7.1.337 following the linked distribution instructions. The commands above are prerequisites, not a substitute for installing K and its matching backend libraries. If the K distribution bundles libraries/toolchain setup, use that setup. No `use-llvm` shell function is required.

Check the resulting environment:

```bash
python3 --version
java -version
kompile --version
command -v kompile kast krun make flock c++
python3 reproduce.py --check-only
```

The replay records the actual tools and build commands. Missing programs, an incompatible K version or build errors produce explicit diagnostics; they are not counted as passing tests. Compilation never uses an archived compiled.bin.

## Resources and optional features

The build limits Java to eight active CPUs and a 2 GiB heap. Replay defaults to four tasks with single-threaded numeric libraries and a bounded JVM; it supports one to eight workers. A Linux machine with 8 logical CPUs and 16 GiB RAM is a reasonable starting point, but this is a recommendation rather than a measured minimum. Provide writable local storage for fresh definitions, parser caches and full outputs, plus writable /tmp/scratch and /tmp/locks.

Haskell regression/proof workflows additionally need K's matching Haskell backend (`kore-exec`, `kore-rpc` as required by that distribution) and Z3. They are optional for the main frozen LLVM experiment. `make test-haskell` and `make prove` are explicit separate commands; historical proof logs are not evidence that a fresh proof has run on your machine.

GDB, LLDB, their source installations, DejaGNU, network access and AI tools are not needed after installing the build dependencies. This artifact reproduces K evaluation and oracle checking on archived contexts; it does not recollect native debugger stops or automatically reconstruct the reviewed dataset from a new upstream version.
