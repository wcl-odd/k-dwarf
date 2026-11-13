KOMPILE ?= kompile
LLVM_DEFINITION ?= build/llvm-kompiled
K_SOURCES := $(wildcard semantics/*.k semantics/*/*.k)

.PHONY: all
all: $(LLVM_DEFINITION)/compiled.bin

# Compilation only. Run the experiment separately with validate.py.
$(LLVM_DEFINITION)/compiled.bin: $(K_SOURCES)
	mkdir -p build/tmp
	flock build/compile.lock bash -c 'set -eu; task_tmp=$$(mktemp -d "$$PWD/build/tmp/kompile-XXXXXX"); trap "rm -rf \"$$task_tmp\"" EXIT; env JAVA_TOOL_OPTIONS="-XX:ActiveProcessorCount=8 -XX:+UseSerialGC -Djava.io.tmpdir=$$task_tmp" K_OPTS="-Xmx2g -Xss1m" GHCRTS="-N1" TMPDIR="$$task_tmp" python3 -c "import os, sys; os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:8]); os.execvp(sys.argv[1], sys.argv[1:])" $(KOMPILE) semantics/dwarf.k --main-module DWARF --syntax-module DWARF-SYNTAX --backend llvm --output-definition "$(LLVM_DEFINITION)" --temp-dir "$$task_tmp/kompile"'
