# 通用配置审查

提供可复用的配置取证与输出边界。具体流程的企业取数脚本、生产字段映射和分析案例不随源码分发。

| 文件 | 用途 |
| --- | --- |
| privacy.py | 指定范围的固定结构整数计数，拒绝自由文本、原始记录和未知字段 |
| review_logic.py | 公式赋值与引用、保存重建线索、分支静态候选 |
| scoped_config.py | 从B02—B05登记方法派生单流程查询，拒绝无边界来源 |
| Read-ScopedConfiguration.ps1 | 按明确流程、名称、表单与可选任务类读取配置，两遍核对 |
| normalize_scoped.py | 将独立采集标准化，不改正式基础批次 |
| Read-ReportAccess.ps1 | 指定模块与表单的列表、共享、字段和状态检查 |

运行单流程读取时提供自己的已确认参数：

    pwsh -File tools/oa-audit/Read-ScopedConfiguration.ps1 -WorkflowId 123 -ExpectedWorkflowName "示例流程" -ExpectedFormId -100 -ConnectionDirectory tools/oa-readonly-db/.local -OutputPath .local/configuration.json

TaskClass可选，未提供时不取得指定任务。输出路径由部署方选择本地目录；原始配置和共享身份不提交Git或直接发送AI。

    python -m unittest discover -s tools/oa-audit/tests -q

privacy.py目前面向既有审查范围，扩展新范围时增加明确字段及合成测试；不要改为任意字典透传。其保护限于调用门禁的入口，不是全系统代理。

静态候选出口、字段引用与保存重建只是检查依据。岗位实际可见、引擎选择、保存读回和业务影响需要对应证据与验收。
