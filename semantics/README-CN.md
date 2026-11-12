# DWARF expression语义：中文说明

正式规则位于domains/、frontend/和execution/，英文完整接口文档见README.md，论文命名对应见paper-naming-audit.md。纯前端负责text／hex解码，执行核心使用已解码表达式及固定只读上下文。当前支持164个DWARF 2–5标准OP名称，不支持厂商扩展；支持整数、受限Boolean以及文档列明的四种DW_ATE_float格式。

运行make llvm编译，然后执行python3 verify.py --output build/verification，离线验证test-corpus/中的冻结样例。K负责解码和执行OP，Python负责上下文供应、属性依赖调度和原断言检查；不启动GDB／LLDB，也不需要原采集目录。单表达式入口仍为run.py。前提不满足时自然stuck；incomplete不自动表示表达式非法。

LLDB 22.1.8的55个核心expression为43通过、12项差异；GDB 17.1的269个为267通过、2项差异。两项LLDB辅助检查单列。最终结果与证据在../output/，精简论文表格在../docs/evaluation/。筛选和断言映射包含人工／AI审阅，固定输入后的复跑不需要AI；不保留历次版本和原生重新采集工具链。
