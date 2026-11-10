# DWARF expression 的 K 学习与实现

本目录用于学习 K Framework，并逐步实现论文中 DWARF expression 的完整语义规则。

当前规则版本为 `paper-names-v1`（内部命名与论文 §3.3／§3.4 对齐，规则定义保持不变）：K 解码前端与执行核心分离，核心以已解码 E 和只读上下文为输入，操作前提不满足时自然 stuck。LLVM／Haskell 构建、回归和 36 条符号性质已验证；随后重跑冻结集，见 [当前报告](output/README.md#validation)。旧归档及人工备注保留。

## 目录

```text
kframework/
├── docs/        项目文档、测试覆盖统计与实验分析
├── paper-results/  精简论文参考：结果、方法、差异及制表数据
├── output/      当前实验的完整证据入口与历史汇总
├── learning/    学习教程、教学语义、运行示例与入门证明
├── semantics/   论文语义规则的正式 K 实现
├── differential/ 上游测试对 K 的验收及 K/LLDB/GDB 差分工具
├── tests/       正式实现的测试输入、预期结果与验证说明
└── build/       编译产物（不纳入 Git）
```

从 [学习教程](learning/README.md) 开始。已有教学材料由原来的 `docs/k-crash-course/` 迁入 `learning/`。

项目文档见 [docs](docs/README.md)。上一轮归档规则验收上游 expression 的结果见 **[LLDB 22.1.8／GDB 17.1](output/appendix.md#history)**；更早的 [LLDB](docs/results/lldb.md)、[GDB](docs/results/gdb.md) 及 [总表](docs/results/test-coverage.md) 保留各自历史口径。

用于论文的当前表格和方法见 [paper-results/](paper-results/README.md)，完整证据由 [output/latest.json](output/latest.json) 指定。旧版双后端实验、补充探针与差异审计见 [历史论文实验数据](docs/results/paper-evaluation.md)，不作为当前结果表。

最新完整运行是 `full-recapture-20261109-201227`：LLDB 55 个核心 expression 中 43 个通过、12 项差异；GDB 269 个中 267 个通过、2 项差异，两来源核心任务均无无法检查项。另列 2 项 LLDB 辅助检查及 248 次 GDB 属性依赖调用，均不增加核心分母。完整 [结果](output/README.md)、[构造方法](output/methodology.md)与[附录](output/appendix.md)保留逐例证据和人工备注；一条 GDB 类型查询没有独立根 expression。

使用 GDB、LLDB 原测试检验 K 的主入口是 `prepare-upstream` / `test-upstream`：前者提取原输入、预期和必要的真实停止点快照，后者仅用 K 和保存的输入检查原断言。见 [上游测试验收](docs/design/upstream-testing.md)。

官方规范：[DWARF Version 5](../paper/references/DWARF5.pdf)，编码依据为 §7.6、表 7.9 和附录 C。实现保留已说明的模运算等建模选择，并不据此宣称与规范整体等价。

正式实现以 [DWARF 5](../paper/references/DWARF5.pdf) 和已记录的建模选择为依据。当前支持 **164 个 DWARF 2–5 标准 OP 名称，不支持厂商扩展 OP**；展开的 lit/reg/breg 各计 32 个名称。支持整数及 DW_ATE_float 的 binary32、binary64、x87 binary80、binary128，包含浮点计算、比较及转换；支持调用、独立入口快照、TLS、地址空间读取和隐式指针身份，具体前提与机制限制见 [实现与范围说明](semantics/README.md)。

阅读执行规则从 [core.k](semantics/execution/core.k) 开始：它以论文第 3 节的已解码 E 和只读上下文为固定输入，直接重写位置、栈和现有片段状态。[dwarf.k](semantics/dwarf.k) 保留 text／hex 集成入口；独立纯前端负责解码和归一化，核心不导入它们。调用与入口值同样使用准备好的子表达式，组装及结果接口保持原状。详见[解码与执行分层](docs/design/decoding-execution.md)。

当前默认构建使用 `build/paper-names-v1/`，支持 164 个标准名称，不支持 GNU／LLVM／Wasm 扩展。Convert 的 generic 源按地址位宽作无符号解释，适用于整数及浮点目标。历史源码、构建哈希、命令与实验汇总保留；已替代的运行数据和旧构建按[清理记录](build/stale-docs-build-cleanup-20261110-v1/README.md)退役。逐 OP 浮点支持与不支持见 [当前支持表](output/appendix.md#floating)。

## 运行正式语义

在本项目根目录 `/home/congleiwang/kframework` 执行：

```bash
make llvm
python3 run.py tests/examples/read.dwarf --context tests/examples/context.json
python3 run.py tests/examples/read.hex --format hex --context tests/examples/context.json
python3 run.py tests/examples/register.hex --format hex --context tests/examples/context.json
python3 run.py tests/examples/composite.hex --format hex --context tests/examples/composite-context.json
python3 run.py tests/examples/conversion.hex --format hex --context tests/examples/conversion-context.json
python3 run.py tests/examples/frame.hex --format hex --context tests/examples/frame-context.json
python3 run.py tests/examples/indexed.hex --format hex --context tests/examples/indexed-context.json --purpose value
python3 run.py tests/examples/countdown.hex --format hex --context tests/examples/context.json --depth 14
make check
```

上下文由独立 JSON 文件提供；具体求值由 K 执行。运行入口保留整个终栈和完整最终配置，新增 `result` 字段保存位置描述结果；未获得结果时报告未完成，`result` 为 null。

与调试器进行差分测试的运行方法、模块和数据流见 [适配层说明](differential/README.md)。已接入 LLDB 内部 DWARF 求值器、GDB 离线目标文件，以及供 breg/deref 使用的共享寄存器和逐字节内存，以及 convert/reinterpret/deref_type 使用的共享类型 ELF；固定帧快照分别供应 CFA 与 frame base。GDB 上下文通过本地只读模拟目标供应，不启动被调试程序；OP 缺失和语义差异作为实验结果保留。

本地上游测试已建立 [来源清单与覆盖核对](differential/upstream/README.md)，历史差分集为 553 例。当前冻结实验已重新采集其涉及的 37 个 GDB 原驱动，LLDB 单元 fixture 由审阅配方重建；新的 LLDB Shell 冻结仍暂不执行。此前接入 14 个 GDB 原脚本及 7 个 LLDB Shell 测试的记录属于历史实验。普通差分命令继续使用离线目标和只读 RSP，其他 fixture 限制单独记录。

控制流使用 `NEXT + signed16` 计算目标，不按地址宽度回绕，只接受操作起点或 END。`bra` 弹出条件，零值落下，非零跳转；目标不可用时保留整个失败现场。向后跳转可以形成循环，运行这类输入时使用 `--depth`；预算耗尽报告 `incomplete`。

## 开始学习

当前环境已安装 K Framework，可直接使用 `kompile`、`krun` 和 `kprove`。在本项目根目录 `/home/congleiwang/kframework` 执行：

```bash
cd learning
mkdir -p ../build
kompile dwarf-mini.k --backend llvm --output-definition ../build/dwarf-mini-llvm-kompiled
krun sub.dwarf --definition ../build/dwarf-mini-llvm-kompiled
```

正式文本输入使用完整 OP 名称，并声明起始偏移与末尾独立 END；整数支持十进制和正负十六进制。原来的无偏移格式已从正式入口移除（独立教学语义仍使用其教学格式）：

```text
0x0: DW_OP_consts -0x1,
0x2: DW_OP_stack_value,
0x3
```

`--format hex` 让 K 直接解析十六进制代码字节，例如 `11 7f 9f`；Python 不解释数字、opcode 或 LEB128。两种模式共用求值规则，`position/end` 是字节位置或文本声明的位置。详见[输入与解码](semantics/README.md#输入与解码)。

正式规则位于 `semantics/`，对应测试位于 `tests/`。编译产物统一放入 `build/`，不同后端使用独立子目录；该路径已加入忽略规则。

## 复合位置与目标架构

`DW_OP_implicit_value [0x11 0x22]` 提供字节值；`DW_OP_piece n` 以字节为单位，`DW_OP_bit_piece n k` 以位为单位。K 保留各片段的位置描述和原始参数，并组装对象。复合结果包含 `bit_size` 和最高位在左的二进制 `bits`，不可用位为 `?`，不是零或通配符。

组装用例需显式提供 `architecture`，支持小端 `i386`（32 位）、`x86_64` 和 `aarch64`（64 位）。每个片段从空栈开始，分隔操作清空整个栈；复合输入必须使用空初始栈。来源长度不足时保持当前现场并报告 incomplete，缺失外部数据则保留未知位。普通地址和独立寄存器结果仍不读取对象。

差分适配分别支持三种目标的 LLDB 模拟上下文及 GDB 只读 RSP 目标。AArch64 实验使用 `--compiler clang --nm llvm-nm --objcopy llvm-objcopy` 和启用 AArch64 的 GDB；报告分别记录对象内容、可用性和位置结构证据。详见 [组装规则](semantics/README.md#隐式字节值与复合组装)。

此前复合组装轮验证：LLVM 68 组、Haskell 新功能 10 组、适配层 30 组及 15 条性质通过。183 例联合差分测试保留全部差异与四例既有 GDB 故障；详情见 [测试记录](tests/README.md#2026-10-30-隐式值与复合组装验证) 和 [差分报告](build/differential/composition-acceptance/report.md)。

上一轮整数转换与类型上下文验证：LLVM 完整 75 组、Haskell 新增 7 组、适配层 35 组及 18 条性质通过。251 例联合差分实验包含 68 个新增类型用例，均在三后端实际运行；没有新增工具故障，四例既有 GDB 故障继续保留。Convert 越界时保持现场；Boolean Convert 尚未定义。详见 [测试记录](tests/README.md#2026-10-30-整数转换与类型上下文验证)、[差分报告](build/differential/conversion-final/report.md) 和 [最终清单](build/conversion-validation.json)。

此前固定帧轮验证：当时支持 150 个 OP，CFA 与 frame base 为独立可选输入；LLVM 80 组、Haskell 新帧 5 组、适配层 41 组及 20 条符号性质通过。339 例联合实验中，66 条上游断言全部满足，无新增工具故障，保留四例既有 GDB 崩溃。见 [实验记录](differential/README.md#2026-10-30-固定帧与上游覆盖验证)、[报告](build/differential/frame-final/report.md) 和 [验证清单](build/frame-validation.json)。

## 地址表、对象地址与值用途

`DW_OP_addrx` 和 `DW_OP_constx` 共用当前 CU 的 `debug_addr` 表；只有 addrx 应用 `debug_addr_load_bias`，二者均构造地址宽度的 generic 位串。`DW_OP_push_object_address` 读取可选的 `object_address`。缺失数据保持现场并报告 incomplete；不会从 SP 或其他属性推导对象地址。

`python3 run.py INPUT --format hex --context CONTEXT --purpose value` 用于数组边界等普通整数表达式，返回 `{"kind":"scalar","value":N,"type":T}` 并保留整个栈。默认 `location` 仍解释位置描述。value 用途不接受 reg、implicit_value、stack_value 或片段描述。基础类型栈值可以宽于地址宽度；常量类 OP 的 generic 结果截断不构成全局栈宽度上限。

当前上游验收以原断言及独立位置证据为依据，主单位是 expression；源码断言位置与属性依赖调用分别计数，见 [当前结果](paper-results/results.md)、[可检查性标准](paper-results/methodology.md)与[采集和离线重放说明](docs/design/upstream-testing.md)。索引查询、对象地址及动态属性依赖均由 K 执行；Python 仅调度属性依赖并观察 K 给出的位置。

## 冻结测试集与当前交付状态

当前使用 LLDB 22.1.8／GDB 17.1 的标准 OP 派生选集，共 324 个核心 expression（55／269）和 2 项 LLDB 辅助任务。初次冻结的断言实例、后续范围修订、根 expression 和依赖调用分别追溯，不能互相替代。选集及比较标准见 [方法说明](paper-results/methodology.md)，最新执行身份见 [output/latest.json](output/latest.json)，逐例差异及人工备注见 [论文限制说明](paper-results/limitations.md)；不以原生 PASS 代替 K 的通过数。

新增上下文可保留物理寄存器宽度、原始类型 DIE 和精确请求响应式 mock 内存。`wasm_locations` 仅为旧归档保留输入兼容，不再有可消费它的 OP。它们用于忠实迁移原 fixture，不默认为所有调试器后端都能供应。前提失败时 K 自然 stuck，不生成错误控制项或额外诊断重写；`stop_reason` 为 null。嵌套失败保留活动表达式及返回项，不回退到调用者。`incomplete` 也可能来自预算耗尽，不能仅据此判定 DWARF 无效。
