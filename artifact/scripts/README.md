# Internal validation scripts

Use `python3 validate.py --output build/experiment` from the project root. These seven modules implement that entry point; they do not need to be run separately.

| File | Responsibility |
| --- | --- |
| `experiment.py` | Parses command-line options, checks the environment, schedules cases with concurrency and resource limits, and writes `report.md`, `expressions.csv`, and `checks.csv`. Keeps execution faults separate from semantic verdicts. |
| `cases.py` | Loads `test-corpus/lldb.json` and `gdb.json`, validates case structure, and prepares each case's bytecode, interface, and requirements. Source annotations are documentation only. |
| `dependencies.py` | Schedules required attribute expressions and observation dependencies through K, then combines their outcomes with the root case's interface and observation inputs. Dependency calls do not add core cases. |
| `k.py` | Invokes `runner.py` for a prepared case, checks the returned protocol and preservation of the supplied expression/interface, and classifies completion or abnormal termination. |
| `runner.py` | Validates and serializes the interface, calls K to parse and evaluate bytecode, and reads the final configuration, stack, location, and diagnostics. Its optional cache stores parsed K inputs, never evaluation results. |
| `requirements.py` | Checks each case's requirement against its K outcome, including location identity, values, types, composite pieces and available bits, and expected abnormal termination. Reads object contents only from the fixed interface. |
| `processes.py` | Runs child processes, saves commands and raw output, enforces timeouts, and terminates owned process groups on interruption or failure. |

The main flow is `validate.py` → `experiment.py` → case preparation and dependency scheduling → `k.py` → `runner.py` → requirement checking and reporting. `processes.py` handles child execution and cleanup.

Only K decodes and executes DWARF operations. Python prepares inputs, schedules calls, observes outcomes, checks requirements, and counts verdicts. The runner does not compile definitions, start debuggers, collect additional interface data, or read the recorded `results/` package. See the [project README](../README.md) for installation, options, exit codes, and output files.
