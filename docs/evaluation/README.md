# Paper reference files

| File | Purpose |
| --- | --- |
| README.md | Directory guide and maintenance |
| results.md | Expression results, LLDB assertions and OP/location/type coverage |
| methodology.md | Canonical selection, extraction and checkability method |
| limitations.md | Differences, exclusions, limits and editable manual notes |
| results.csv | Machine-generated result and coverage rows |
| summary.json | Metrics, identities and evidence references |

Read results, methodology and limitations together. Methodology and manual notes are maintained here; exports preserve them. Full configurations are in ../../output, and frozen inputs in ../../test-corpus. Full evidence is local and is included in the artifact, not required in a development Git clone. Links to output/ require that package to be restored.

Re-export with `python3 -m verification.paper_results --output NEW-DIRECTORY`. Existing destinations are refused. The exporter reads the recorded result package and does not run K or debuggers. Notes default to this directory; use --notes to import another limitations.md.
