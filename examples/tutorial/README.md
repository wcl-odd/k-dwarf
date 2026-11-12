# 面向 DWARF expression 论文的 K 速成

This tutorial accompanies Section 3 of the paper. It introduces executable small-step rules and symbolic properties; the tutorial K definition is separate from the full formal semantics.

## 1. 先理解 K 在论文中承担什么

K 是定义语言语义的框架。你给出语法、配置和重写规则，工具可以编译这些定义、执行具体输入，并在适当的后端和证明条件下处理符号性质。

```text
DWARF 规范 + 论文的建模选择
             ↓ 由你编码
          K 语义定义
             ├─ kompile → krun：运行具体表达式
             └─ kompile → kprove：检查你提出的可达性 claim
```

`kompile` 编译的是语义定义；`krun` 输入的是这个定义所描述的程序。K 不会从 DWARF 标准自动生成正确的规则，也不会把 `calc` 这个名字自动补成完整的机器整数运算。

论文定义到 K 的建议对应：

| 论文概念 | K 中的表示 | 要保留的约定 |
| --- | --- | --- |
| 抽象操作 `const`、`breg`、`binary` | `syntax` 声明的构造子 | 不必从原始 opcode 和 LEB128 解码开始 |
| 栈值 `〈n,τ〉` | 如 `val(Int, Ty)` | 数值与原始类型标识均保留 |
| `S` | `<stack>` cell，内容可用 `List` | 本文栈顶在右 |
| `E`、`op_E(p)` | 只读代码映射，如 `<code>` | 按原始字节偏移查询指令 |
| `p`、`next(p)`、`ℓ(E)` | `<pc>`、后继映射、结束偏移 | 表达式偏移与目标程序 PC 分开 |
| `Γ` | 若干只读 context cells 或明确的查询函数 | 目标状态快照在当前求值期间不变 |
| `Γ ⊢ C → C′` | `rule` | 左侧匹配配置，右侧给出变化，`requires` 对应条件 |
| `calc_τ` 等辅助计算 | 有计算规则的 `[function]` | 位宽、符号解释和定义域由你实现 |
| `Γ ⊢ E ⇓loc R` | 显式结果构造子与结果 cell | `memory(a)`、`register(r)` 和 `value(v)` 分开 |

这里的 cell 是状态中的命名字段，用 XML 形状书写，不是在调用 XML 处理器。存入配置的 `Γ` 不一定要变化：在规则中只匹配、不重写相应 cells，就能把它们作为只读上下文使用。

## 2. 第一课：先运行四条操作

文件 `dwarf-mini.k` 定义 `DW_OP_constu`、`DW_OP_consts`、`DW_OP_minus`、`DW_OP_dup`、`DW_OP_drop`。输入使用完整的操作名称，操作之间用逗号分隔，操作与参数之间用空格分隔，无参数的操作直接写名称；不需要括号、分号或末尾的 `.Program`。输入是解码后的文本，不是 DWARF 字节编码。

```k
syntax Instr ::= "DW_OP_constu" Int
               | "DW_OP_consts" Int
               | "DW_OP_minus"
               | "DW_OP_dup"
               | "DW_OP_drop"
syntax Program ::= List{Instr, ","}
```

`List{Instr, ","}` 定义逗号分隔的操作列表，支持单条操作及空列表；`.Program` 是 K 中使用的空列表项，普通输入不需要写它。`DW_OP_constu` 接受地址位宽内的无符号整数，`DW_OP_consts` 接受该位宽内的有符号整数；两者均压入 generic 类型值。

```bash
cd examples/tutorial
mkdir -p ../../build
kompile dwarf-mini.k --backend llvm --output-definition ../../build/dwarf-mini-llvm-kompiled
krun sub.dwarf --definition ../../build/dwarf-mini-llvm-kompiled --color off
```

本环境已经安装 K，先不用重新安装。`--backend llvm` 适合这里的具体执行；后面用 Haskell 后端演示证明。不同后端的具体能力取决于 K 版本及配置。

`sub.dwarf` 的内容是：

```text
DW_OP_constu 5, DW_OP_constu 3, DW_OP_minus
```

执行过程是：

```text
[] → [〈5,g〉] → [〈5,g〉,〈3,g〉] → [〈2,g〉]
```

输出会打印整个配置。正常结束时 `<k>` 中是 `.K`，`<stack>` 中是 `ListItem(val(2,g))`。

再逐条执行以下输入：

```bash
krun wrap.dwarf --definition ../../build/dwarf-mini-llvm-kompiled --color off
krun stack.dwarf --definition ../../build/dwarf-mini-llvm-kompiled --color off
krun stuck.dwarf --definition ../../build/dwarf-mini-llvm-kompiled --color off
```

| 输入 | 应观察到什么 | 学习重点 |
| --- | --- | --- |
| `sub.dwarf` | 栈顶 `val(2,g)`，`<k>` 为空 | 操作数顺序是次栈顶减栈顶 |
| `wrap.dwarf` | 栈顶 `val(18446744073709551615,g)` | `0−1` 按 64 位回绕 |
| `stack.dwarf` | 栈顶 `val(7,g)` | `DW_OP_dup, DW_OP_drop` 保留原来的栈 |
| `stuck.dwarf` | `<k>` 仍有 `DW_OP_minus`，栈为空 | 没有规则可用不等于正常结束 |

本例没有错误结果构造子。即使 `krun` 成功打印了配置、进程返回 0，也要检查是否达到了定义中的完成状态。完整模型还要区分缺失上下文、不支持的计算、规范未定义情形和执行预算耗尽，不能统一解释为输入无效。

## 3. 读懂一条规则就能开始移植

核心减法规则如下，完整代码见 `dwarf-mini.k`：

```
rule [sub]:
  <k> DW_OP_minus => .K ... </k>
  <stack> S ListItem(val(N2, g)) ListItem(val(N1, g))
       => S ListItem(val((N2 -Int N1) modInt (2 ^Int A), g))
  </stack>
  <width> A </width>
```

逐项阅读：

1. `rule [sub]:` 为规则命名。大写的 `S`、`N1`、`N2`、`A` 是模式变量。
2. `<k>` 是待执行计算。`DW_OP_minus => .K` 消耗当前指令；`...` 保留后续计算。
3. `<stack>` 左边匹配任意前缀 `S` 和最后两个条目，右边保留 `S` 并压入结果。两个 cell 中的变化属于同一次规则应用。
4. 同一个变量名在一条规则中必须取同一个值。将来的 typed binary 规则可用相同的类型变量匹配两个条目，表达原始类型必须相同。
5. `<width> A </width>` 没有 `=>`，表示读取、不修改。
6. `-Int` 是数学整数减法；`modInt (2 ^Int A)` 显式落实有限位宽。K 的 `Int` 本身不会自动发生机器整数溢出。

`modInt` 对正模数产生非负余数，适合本例 generic 减法的 unsigned representative。K 的 `%Int` 对应向零取整除法的余数；对于负数，两者不同。你论文中的除法与余数采用向零取整，应按具体运算选择 `/Int`、`%Int`，并编码非零及溢出条件，不能把所有计算都替换成 `modInt`。

再读其余几个符号：

| 记号 | 含义 |
| --- | --- |
| `syntax` | 定义可用的数据或程序语法；本身不赋予执行行为 |
| `configuration` | 定义初始状态结构 |
| `$PGM:Program` | 工具从输入文件解析出的初始程序 |
| `.List` / `ListItem(V)` | 空列表 / 一个列表元素 |
| `.K` / `~>` | 空计算 / 内部计算顺序，如 `DW_OP_dup ~> DW_OP_drop` |
| `requires P` | 规则适用条件 |
| `[function]` | 定义用于求值的辅助函数，仍需提供计算规则 |
| `claim` | 待验证的性质；不是新增一条执行规则 |

本例将源程序列表中的 `Instr , Program` 转成 `~>` 内部计算序列，因此还包含取下一条指令的辅助规则。输入文件使用逗号，`~>` 只用于 K 规则中的计算序列。`krun --depth N` 限制的是 K 重写步，不能直接解释为 N 条 DWARF 指令。

读到这里，做一个小练习：参照减法规则加入 `DW_OP_plus`，然后运行 `DW_OP_constu 18446744073709551615, DW_OP_constu 1, DW_OP_plus`，结果应为 `val(0,g)`。这会同时检验你是否理解语法声明、规则匹配和回绕。

## 4. 第二课：把执行与证明分开

具体执行回答“这个输入的结果是什么”。符号证明可以讨论满足前提的一组初始状态。

`dup-drop-spec.k` 中的性质是：

```
claim [dup-drop]:
  <k> DW_OP_dup ~> DW_OP_drop => .K </k>
  <stack> ListItem(val(N:Int, g))
       => ListItem(val(N, g)) </stack>
```

它表示：初始栈只有一个 generic 值时，执行 `DW_OP_dup, DW_OP_drop` 可以完成，并保持该栈。`N` 是符号变量；这比只运行 `DW_OP_constu 7, DW_OP_dup, DW_OP_drop` 覆盖的状态更多。规则不需要数值运算，因此这个性质不需要给 `N` 加位宽约束；它并不据此宣称任意整数都是合法 DWARF 栈值。这里先证明单元素栈，推广到任意栈前缀是后续练习。

```bash
kompile dwarf-mini.k --backend haskell --output-definition ../../build/dwarf-mini-haskell-kompiled
kprove dup-drop-spec.k --definition ../../build/dwarf-mini-haskell-kompiled --spec-module DUP-DROP-SPEC
```

本教程于 2026-10-29 更新输入语法后在当前环境的 K v7.1.337 上检查：LLVM 和 Haskell 定义均编译成功，上述四个具体执行例子得到表中结果，`kprove` 返回 `#Top`、退出码 0。

理解结论边界：通过这个 claim 只说明该性质在当前 K 定义下成立。它不能证明当前定义符合 DWARF 规范，也不能证明整个解释器正确。

`kprove` 的 reachability 证明还涉及路径量化和终止约定。不要把默认的 all-path claim 直接写成“所有执行都终止”的总正确性结论；有循环时，终止性要另行论证。这里的 `DW_OP_dup, DW_OP_drop` 只有有限步，可以直接核对其终止。

## 5. 正式移植这篇论文时怎样组织

### 先加入字节偏移，再扩展跳转

第一课的 `<k>` 直接保存剩余指令，适合理解直线片段。正式实现建议保存不可变的代码映射，用 `<pc>` 记录当前表达式字节偏移，并保留 `<end>` 与指令后继信息。

可以让 `<k>` 中运行一个内部任务 `#step`：根据 `<pc>` 查询操作，执行后更新 `<pc>`，再进行下一步。当 `<pc>` 等于表达式结束偏移时进入完成状态。若拆成取指和执行两条 K 规则，就需要在论文到 K 的对应关系中说明这些辅助步。

你的 `bra(d)` 目标是 `next(p)+d`，不能写成“当前指令序号加 d”，也不能从指令开头计算。实际跳转目标须为当前表达式的操作边界或结束边界。条件为零时按 BraFalse 顺序执行，不应额外要求那个未采用的跳转目标有效。

### 按已有论文的机制逐层扩展

| 顺序 | 加入什么 | 应先核对的例子或性质 |
| --- | --- | --- |
| 1 | 显式 `E,p,S`、`const`、栈操作 | 单步对应；保留底层栈前缀 |
| 2 | 类型元信息及整数函数 | 减法顺序、generic 有符号比较、回绕、移位边界 |
| 3 | `bra`、`skip` | 两条条件分支、指令内部目标、结束边界、回边 |
| 4 | `breg`、`deref` 和部分上下文查询 | 查询成功与上下文缺失的不同处理 |
| 5 | 位置描述结果 | 相同数字分别作为地址和直接值；`reg` 与 `breg` |
| 6 | `entry`、表达式调用、pieces | 嵌套求值的栈、上下文、返回及片段边界 |

你的章中有几个尤其需要保留的区别：

- `reg(r)` 返回寄存器位置，不读取寄存器数值；`breg(r,d)` 才从上下文取值并计算。
- 普通栈求值结束返回整个栈，不强制恰好一个元素。`entry` 的嵌入表达式则要求独立空栈起步并恰好返回一个值。
- `stack_value` 返回直接值并终止当前 simple description；它不是将一个普通数值压栈的指令，也不是自动进行一次内存读取。
- 基类型身份必须保留；不能把相同位宽和 signedness 的不同类型直接合并。
- 片段分别从空栈开始，保留原始元数据。位置求值结果与后续的对象读取、片段组装分开实现。

论文中的嵌套大步前提，例如 `EntryExpr`，不能仅在 K 规则中引用 `⇓` 就期待自动执行。通常需显式保存外层配置、切换到入口上下文和独立栈，执行子表达式，再检查返回栈并恢复外层；也可以采用另一个已明确定义的可执行求值机制。表达式调用与 entry 的栈约定不同，应分别实现。

上下文暂时可以用小型 maps 提供：先手工构造寄存器和内存查询结果，晚些再接 ELF/DWARF 读取工具。内存的数值加类型接口可以遵循论文抽象边界，不必为了学习 K 立即展开字节序和存储表示。

## 6. 建议的学习节奏与论文产出

下列是学习安排，不是全 DWARF 实现的工期承诺。

| 阶段 | 学习任务 | 可检查的成果 |
| --- | --- | --- |
| 第 1 天 | 运行本例，读懂 cells、模式匹配、`requires`，自己加 `DW_OP_plus` | 会从最终配置判断完成或卡住 |
| 第 2 天 | 将 `E,p,S` 显式化，加入跳转与小型上下文 | 能运行论文示例的两条控制流路径 |
| 第 3 天 | 加入原始类型、位宽函数及 location results | 数值、地址和寄存器位置不会混淆 |
| 第 4 天 | 跑通本例 claim，写一个有前提的自选性质 | 区分执行样例与符号证明 |
| 第 5 天及以后 | 核对规则对应和范围，逐步接入验证实验 | 可复现的定义、输入、结果与覆盖清单 |

论文最有用的配套材料是一张“规范依据—论文规则—K 规则或函数—支持条件—验证材料”的对应表。将规范明确要求、本文建模选择和尚未支持的行为分别记录。K 可执行性、性质证明和与规范的一致性各自需要证据。

如果要论证 K 实现对应论文中的数学关系，应给出状态对应和适用不变量，并解释计算辅助函数及取指辅助步的关系。编译成功和例子通过不足以代替这个论证。

官方进一步学习入口：[K User Manual](https://kframework.org/docs/) 和 [K Tutorial](https://kframework.org/k-distribution/k-tutorial/)。优先学习配置、规则、集合、辅助函数和符号证明；涉及表达式求值顺序的 heating/cooling 与 `strict` 属性可以稍后学习，本例用显式指令顺序即可起步。
