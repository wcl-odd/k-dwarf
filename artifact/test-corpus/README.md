# Expression cases

lldb.json and gdb.json contain the complete, self-contained inputs for their respective sources. Each expression case consists of expression bytecode, a fixed external input interface, and a requirement on the K outcome. Source file names, test names, and original assertion quotations are documentation only; the runner never opens them.

The group field separates core expression cases from auxiliary checks; it is used only for reporting and is not supplied to K. Dependencies belong to their root case and do not enlarge the denominator. Requirements come from upstream tests or independently observed native addresses or registers; expected results are never inferred from K. An absent interface entry remains unknown; an empty bytecode string is a genuine empty expression.

See the project README for selection, installation, parallel execution, and result files. Detailed selection and input-collection records are maintained separately from this project.
