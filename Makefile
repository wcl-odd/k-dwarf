KOMPILE ?= kompile
KPROVE ?= kprove
PYTHON ?= python3
K_SOURCES := $(wildcard semantics/*.k semantics/*/*.k)
LLVM_DEFINITION ?= build/llvm-kompiled
HASKELL_DEFINITION ?= build/haskell-kompiled

CORE_LLVM_DEFINITION ?= build/core-llvm-kompiled
CORE_HASKELL_DEFINITION ?= build/core-haskell-kompiled
CORE_SOURCES := semantics/execution/core.k semantics/execution/runtime.k semantics/execution/composition.k semantics/execution/expression.k semantics/execution/computations.k semantics/execution/floating.k semantics/domains/dwarf-domains.k

.PHONY: llvm haskell core-llvm core-haskell test test-haskell prove check verification-test

llvm: $(LLVM_DEFINITION)/compiled.bin

haskell: $(HASKELL_DEFINITION)/compiled.bin

# Shared compilation outputs are serialized, including under make -j.
# A private scratch directory and bounded JVM keep concurrent workspaces safe.
define compile_definition
	mkdir -p /tmp/locks /tmp/scratch
	flock /tmp/locks/kframework.lock bash -c 'set -eu; task_tmp=$$(mktemp -d /tmp/scratch/kframework-kompile-XXXXXX); env JAVA_TOOL_OPTIONS="-XX:ActiveProcessorCount=8 -XX:+UseSerialGC -Djava.io.tmpdir=$$task_tmp" K_OPTS="-Xmx2g -Xss1m" GHCRTS="-N1" TMPDIR="$$task_tmp" python3 -c "import os, sys; os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:8]); os.execvp(sys.argv[1], sys.argv[1:])" $(KOMPILE) $(1) --main-module $(2) --syntax-module $(3) --backend $(4) --output-definition $(5) --temp-dir "$$task_tmp/kompile"'
endef

$(LLVM_DEFINITION)/compiled.bin: $(K_SOURCES)
	$(call compile_definition,semantics/dwarf.k,DWARF,DWARF-SYNTAX,llvm,$(LLVM_DEFINITION))

$(HASKELL_DEFINITION)/compiled.bin: $(K_SOURCES)
	$(call compile_definition,semantics/dwarf.k,DWARF,DWARF-SYNTAX,haskell,$(HASKELL_DEFINITION))

core-llvm: $(CORE_LLVM_DEFINITION)/compiled.bin
core-haskell: $(CORE_HASKELL_DEFINITION)/compiled.bin

$(CORE_LLVM_DEFINITION)/compiled.bin: $(CORE_SOURCES)
	$(call compile_definition,semantics/execution/core.k,DWARF-CORE,DWARF-CORE,llvm,$(CORE_LLVM_DEFINITION))

$(CORE_HASKELL_DEFINITION)/compiled.bin: $(CORE_SOURCES)
	$(call compile_definition,semantics/execution/core.k,DWARF-CORE,DWARF-CORE,haskell,$(CORE_HASKELL_DEFINITION))

test: llvm core-llvm
	DWARF_DEFINITION=$(abspath $(LLVM_DEFINITION)) $(PYTHON) -m unittest discover -s tests/semantics -p 'test_*.py' -v

test-haskell: haskell core-haskell
	DWARF_DEFINITION=$(abspath $(HASKELL_DEFINITION)) $(PYTHON) -m unittest discover -s tests/semantics -p 'test_*.py' -v

prove: haskell core-haskell
	$(KPROVE) tests/proofs/basic-spec.k --definition $(CORE_HASKELL_DEFINITION) --spec-module BASIC-SPEC
	$(KPROVE) tests/proofs/decoding-spec.k --definition $(HASKELL_DEFINITION) --spec-module DECODING-SPEC
	$(KPROVE) tests/proofs/control-flow-spec.k --definition $(CORE_HASKELL_DEFINITION) --spec-module CONTROL-FLOW-SPEC
	$(KPROVE) tests/proofs/register-spec.k --definition $(CORE_HASKELL_DEFINITION) --spec-module REGISTER-SPEC
	$(KPROVE) tests/proofs/composition-spec.k --definition $(CORE_HASKELL_DEFINITION) --spec-module COMPOSITION-SPEC
	$(KPROVE) tests/proofs/conversion-spec.k --definition $(CORE_HASKELL_DEFINITION) --spec-module CONVERSION-SPEC
	$(KPROVE) tests/proofs/frame-spec.k --definition $(CORE_HASKELL_DEFINITION) --spec-module FRAME-SPEC
	$(KPROVE) tests/proofs/external-values-spec.k --definition $(CORE_HASKELL_DEFINITION) --spec-module EXTERNAL-VALUES-SPEC
	$(KPROVE) tests/proofs/upstream-fixtures-spec.k --definition $(CORE_HASKELL_DEFINITION) --spec-module UPSTREAM-FIXTURES-SPEC
	$(KPROVE) tests/proofs/runtime-spec.k --definition $(CORE_HASKELL_DEFINITION) --spec-module RUNTIME-SPEC
	$(KPROVE) tests/proofs/floating-spec.k --definition $(CORE_HASKELL_DEFINITION) --spec-module FLOATING-SPEC

	$(KPROVE) tests/proofs/stuck-spec.k --definition $(CORE_HASKELL_DEFINITION) --spec-module STUCK-SPEC

check: test prove

# Adapter checks are separate from the formal K acceptance/proof suite.
verification-test:
	mkdir -p /tmp/scratch
	artifact_test_tmp=$$(mktemp -d /tmp/scratch/kframework-adapter-tests-XXXXXX); TMPDIR=$$artifact_test_tmp DWARF_INPUT_TMPDIR=$$artifact_test_tmp PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -B -m unittest discover -s tests/verification -v

# BEGIN DEVELOPMENT ARTIFACT TARGETS
.PHONY: artifact artifact-check artifact-source-check artifact-test
artifact:
	$(PYTHON) tools/package_artifact.py
artifact-check:
	$(PYTHON) tools/package_artifact.py --check
artifact-source-check:
	$(PYTHON) tools/package_artifact.py --rules-only --if-present
artifact-test:
	mkdir -p /tmp/scratch
	package_tmp=$$(mktemp -d /tmp/scratch/kframework-packaging-tests-XXXXXX); TMPDIR=$$package_tmp PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -B -m unittest discover -s tests/packaging -v
$(LLVM_DEFINITION)/compiled.bin $(HASKELL_DEFINITION)/compiled.bin $(CORE_LLVM_DEFINITION)/compiled.bin $(CORE_HASKELL_DEFINITION)/compiled.bin: | artifact-source-check
# END DEVELOPMENT ARTIFACT TARGETS
