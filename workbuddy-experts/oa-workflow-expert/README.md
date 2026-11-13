# 泛微流程分析专家 · WorkBuddy

作者：Ecology9AI Maintainers（maintainers@example.invalid）｜版本：1.0.0｜分类：项目质量

上传泛微E9 `.wewf` 或流程XML，离线提取流程配置与证据，再由专家生成包含流程图、办理规则、问题分析和优化建议的中文说明书。适用于审批规则梳理、配置交接、脚本排查和定向接口分析。

## 包含什么

- `.codebuddy-plugin/plugin.json`：专家与市场展示配置。
- `agents/oa-workflow-analyst.md`：中文专家指令，预加载内置技能。
- `skills/oa-workflow-analysis`：离线解析器、分段读取助手、分析方法和公开质量清单。
- `avatars/expert.png`：512×512专业插画头像。

无须OA账号、数据库、外部MCP或模型API密钥。包内不含企业流程、分析结果、人员快照、虚拟环境或第三方二进制依赖。

## 在WorkBuddy中使用

本ZIP按官方专家规范组织，保留一层 `oa-workflow-expert/` 根目录。用于开放平台的专家创建/提交包入口；具体按钮以当前账号界面为准。本地结构校验和解析器测试不等于平台审核或导入成功，上传后仍需在WorkBuddy中实际召唤一次验证。

召唤专家后上传文件，例如：

> 解析这个泛微流程文件，生成包含流程图、办理规则和优化建议的中文说明书。

或提供本地源码路径，要求关联接口实现。只做一处字段或脚本排查时可直接描述问题，不必每次生成完整说明书。

输出到用户工作目录中的独立结果目录；解析器产物保留原状，专家写的说明书位于 `interpretations`。默认交付一份完整说明书，不让用户必须阅读原始JSON或62条审查清单。

## 运行环境

需要目标WorkBuddy环境提供文件读取/写入和命令行能力、Python 3.10+，以及 `lxml>=4.9`、`cryptography>=41`。Python不随包分发；本包不要求特定产品的Python安装路径。`.exml`加密格式当前不支持。

先在命令行确认Python版本并检查依赖：

```text
python --version
python -c "import lxml, cryptography; print('dependencies ready')"
```

Windows可能需要用 `py -3`代替 `python`；macOS/Linux可能需要 `python3`。若缺依赖，建议创建任务专用环境，避免更改全局Python。下面Windows PowerShell中的两个路径需替换为实际插件安装路径和可写的任务目录：

```powershell
$expertHome = 'C:\实际安装目录\oa-workflow-expert'
$taskHome = 'C:\实际任务目录\oa-analysis'
$toolHome = Join-Path $expertHome 'skills\oa-workflow-analysis\scripts\analyzer'
py -3 -m venv (Join-Path $taskHome '.venv')
$taskPython = Join-Path $taskHome '.venv\Scripts\python.exe'
& $taskPython -m pip install $toolHome
& $taskPython (Join-Path $toolHome 'run.py') 'C:\实际文件目录\示例.wewf' --output (Join-Path $taskHome 'reports')
```

macOS/Linux使用等价的 `python3 -m venv <task-dir>/.venv`和 `.venv/bin/python -m pip install <tool-dir>`。依赖安装可能联网访问包源，之后流程解析本身离线。基础PDF需额外安装 `reportlab>=4`，并不等于专家说明书已完成。

没有Python、依赖安装受限或目标端不提供命令行时，专家会报告具体环境缺口，不用猜测结果代替解析。

## 能力与边界

可提取节点、路径、字段/权限、操作人、布局、公式、联动、带入、脚本、Action、编号和撤回等配置。解析器暂未解释的表保留证据；路径读取助手可关联独立路由规则，多个规则组合和平台开关仍需对应版本证据。`partial`不是120个缺陷之类的审计结论，`parsed`也不是运行验证。

真正的卡点、等待时间、接口结果和部署状态需要用户另外提供授权运行资料。本专家不会自动连接OA、执行导出脚本/SQL、调用流程导入或业务写接口。

## 开发与校验

包内 `package-manifest.json`列出文件大小和SHA-256，可检测内容变化；不证明来源或平台审核结果。开发仓库的 `build_expert.py`检查官方元数据要求、资源和路径，生成ZIP。`tests/test_inspector.py`覆盖规则表关联、脚本分页、停用状态、证据裁剪和不存在引用。

规范依据：

- [WorkBuddy专家规范](https://open.workbuddy.cn/docs/expert)
- [WorkBuddy技能规范](https://open.workbuddy.cn/docs/skill)

2026年11月2日核对现行文档。示例ZIP只参考组织方式；Agent未复制其旧tools字段与过期分类。本头像使用内置imagegen生成，再作尺寸归一化；创作描述：深蓝西装、圆框眼镜的东亚流程分析师，浅蓝工作流背景，无文字和商标。
