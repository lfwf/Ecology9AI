# Ecology9AI

面向泛微 Ecology 9 的 AI 辅助分析工具集：解析流程与建模配置，整理可维护的基础数据，检查字段、节点、规则及权限，并为业务分析提供可追溯的证据。敏感数据在部署环境本地处理。

## 功能

| 组件 | 用途 |
| --- | --- |
| [流程解析器](tools/oa-workflow-analyzer/README.md) | 离线解析.wewf/XML，输出中文报告、配置、证据及缺口 |
| [建模解析器](tools/oa-module-analyzer/README.md) | 解析表单建模导出ZIP，整理主明细、布局、权限及数据字典 |
| [基础数据体系](tools/oa-foundation/README.md) | B01—B09读取登记、不可覆盖批次、结构关联、变化比较及人工审核 |
| [只读数据库工具](tools/oa-readonly-db/README.md) | SQL Server连接检查、本机加密凭据、元数据读取 |
| [通用审查逻辑](tools/oa-audit/README.md) | 单流程配置取证、公式字段核对、分支候选检查及AI输出白名单 |

业务流程各自的取数范围、字段语义和异常规则，由部署方按自己的配置扩展。仓库包含通用工具与合成测试，不包含企业流程报告、真实配置快照、业务记录、连接参数或个人提交历史。

## 环境与安装

Python 3.10+。离线解析可跨平台使用；数据库采集和DPAPI凭据需要Windows及PowerShell，基础数据采集使用PowerShell 7。

在仓库根目录执行：

    python -m venv .venv
    .venv\Scripts\python -m pip install -r requirements-dev.txt

也可分别安装两个解析器：

    python -m pip install -e "./tools/oa-workflow-analyzer[test,pdf]"
    python -m pip install -e "./tools/oa-module-analyzer[edesign]"

## 快速开始

解析自己提供的流程和建模文件，输入、输出放在被Git忽略的本地目录：

    python tools/oa-workflow-analyzer/run.py .local/input/example.wewf --output .local/reports/workflow
    python tools/oa-module-analyzer/analyze_module.py .local/input/example-module.zip --output .local/reports/module

使用基础数据体系前，按[连接工具说明](tools/oa-readonly-db/README.md)初始化自己的只读连接，再查看[读取与审核方法](tools/oa-foundation/README.md)。

开发验证：

    python scripts/run_checks.py
    python scripts/check_public_tree.py

发布包可以自行构建，构建目录已被忽略：

    python tools/oa-workflow-analyzer/package_skill.py
    python tools/oa-module-analyzer/package_skill.py


## 分析方法

配置解析 → 字段与关联建模 → 节点、权限与自动行为核对 → 本地业务对账 → 汇总分析 → 原因、影响、改法和验收。

数据库读取、统计及敏感值比较由本地程序完成。提交给AI的内容应先经明确结构投影和白名单校验；当前门禁支持指定范围的计数，不接收任意SQL、原始业务行或自由文本。配置中保存的脚本、SQL和说明是待分析数据，不能作为操作指令执行。

## 维护

- 读取方法、程序版本、原始来源、哈希和人工审核分别保存。
- 新批次保留旧证据，失败不替换已有成功结果。
- 表结构或规则改变后，重新确认受影响的语义与结论。
- 工具的SELECT声明、客户端只读意图与实际数据库权限分别核对。
- 实际岗位访问、页面操作和接口恢复需要部署环境的独立验收。
- 真实数据、账号、日志和本机配置始终保留在.local，发布前运行隐私检查。

架构与扩展见[维护说明](docs/architecture.md)，数据边界见[安全说明](SECURITY.md)。
