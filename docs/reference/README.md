# Support and reviewed selection evidence

| File/directory | Purpose |
| --- | --- |
| implementation.md | Implemented OP/type/context scope and limitations |
| support/ops.csv | 164 standard OP names, rule references and premises |
| support/floating-ops.json | Per-OP floating support, nonapplicability and limits |
| selection/ | Final reviewed selection, exclusions, scope and unextracted query |
| differences.json | Reviewed explanations for existing differences and auxiliary checks |
| manual-notes.json | Preserved expression-identity note inventory |

These are source-controlled review/reference inputs, separate from machine-generated K results. Original source versions, selection hashes and upstream assertion mappings remain in [test-corpus/](../../test-corpus/README.md). Selection records can contain historical absolute paths as provenance; they are not runtime dependencies. Code references in support catalogs are repository-relative; validation_evidence paths in the floating catalog are repository-relative and require the local output/ package.

For editable paper notes use [evaluation/limitations.md](../evaluation/limitations.md); the exporter merges these by stable expression identity with the complete original note inventory. The [methodology](../evaluation/methodology.md) explains review decisions and script/AI roles. Full original configurations and regression/proof logs are in the optional local output/ package. Result manifests authenticate these reference inputs separately from run evidence.
