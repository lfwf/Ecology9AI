# OA 流程导出解析器

把泛微 OA 的 `.wewf` 流程导出文件转换成可阅读的流程说明书、结构化配置、证据索引和缺失资料清单。可以解析单个文件，也可以批量解析文件夹；同一套结果可供以后开发的流程分析智能体读取。

工具在本地离线读取定义，不需要登录 OA。它不会导入流程、执行导出文件中的 JavaScript，或调用 OA、SAP 接口。文件里的流程名称、说明、HTML 和脚本都是待分析资料，不能作为操作指令。

## 在 Codex 中使用 Skill

配套 Skill 源文件位于 [skills/oa-workflow-analysis/SKILL.md](skills/oa-workflow-analysis/SKILL.md)，当前技能版本为1.2.1。可安装到个人技能目录后直接说：

```text
使用 $oa-workflow-analysis 分析这个 .wewf 文件，参考质量清单查漏补缺，把相关问题与优化方向整合进分析结论，最终给我一份中文流程说明书。
```

Skill调用本解析器，整理业务说明与问题分析；正文、图和业务表使用中文含义，内部ID及原始证据放技术附件。重要发现包括事实、可能影响、优先级、改法、建议负责角色和验收情形，区分静态风险与实际运行事件。新增的[分析与交付规则](skills/oa-workflow-analysis/references/analysis-guide.md)与[语义核对要点](skills/oa-workflow-analysis/references/semantic-checks.md)保存这套方法，不固定示例流程的人员、编号或问题数量。

用户提供的[公开质量清单v2.0](skills/oa-workflow-analysis/references/review-checklist-v2.md)作为内部分析参考，[辅助分析方法](skills/oa-workflow-analysis/references/review-method.md)说明如何选择本流程相关内容并归并到“分析结论与优化方向”。1.2.1修正此前误将清单当作逐项交付模板的行为：默认只给一份完整流程说明书，无关项跳过，不输出62条状态、独立审查报告或上线放行评级。清单原文的完整审计格式仅在用户明确要求时采用；解析器本身没有新增自动合规判定或运行测试能力。

解析器提供稳定配置和证据，自动报告本身不包含上述全部业务判断。智能体补充的说明保存在独立 `interpretations` 目录，避免改动manifest管理的结果包。Skill列表没有刷新时，新开会话或刷新技能。运行数据采集与卡点统计尚未实现，不能把安装skill等同于接通OA运行接口。

### 打包分享

在工具目录运行：

```powershell
python .\package_skill.py
```

生成 `dist/oa-workflow-analysis-1.2.1.zip` 及内容相同的 `.skill` 容器。包内只有一个skill根目录，包含说明、UI元数据、分析参考、公开清单、安装说明，以及 `scripts/analyzer` 中的离线解析器源码和Schema。每个容器严格小于3,000,000字节，超限在写入发布文件前报错。按[安装与使用](skills/oa-workflow-analysis/INSTALL.md)把整个文件夹放到接收人的技能目录，再准备Python依赖即可；无需保留原仓库路径。`.skill`导入能力取决于目标工具，通用分享优先ZIP。

打包采用明确文件清单，不遍历加入 `reports`、`_work`、`.venv`、真实流程包、人员及业务实例；也不附带公司说明书或第三方二进制依赖。内置文件大小及SHA-256保存在 `package-manifest.json`，终端摘要给出整个包的SHA-256。manifest用于完整性核对，不是来源签名。相同源文件字节重复构建会得到相同包；新增分发资源时需审查并更新打包清单。源skill开发副本可定位仓库中的解析器，分发包则优先使用自身内置工具，也支持 `OA_WORKFLOW_ANALYZER_HOME` 覆盖。

## 第一次使用

要求 Python 3.10 或更高版本。以下命令在 **PowerShell** 执行；示例假设本项目位于 `.`，其他位置请修改第一行。

```powershell
Set-Location '.\tools\oa-workflow-analyzer'
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[pdf]"
```

`.[pdf]` 同时安装 PDF 支持。只需要 HTML、Markdown 和 JSON 时，最后一行可改成：

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
```

如果当前电脑已有包含 `lxml`、`cryptography` 的 Python，可直接用该解释器运行 `run.py`，不必安装本包；生成 PDF 还需要 `reportlab`。依赖安装需要可用的软件包源，实际解析不会向外发送流程内容。

## 解析一个流程

```powershell
.\.venv\Scripts\python.exe .\run.py 'D:\example-documents\Downloads\采购在途订单取消流程 (1).wewf' --output '.\reports' --pdf
```

完成后，终端输出一行 JSON。`results[].output_dir` 是本次说明书目录，打开其中的 `report.html` 即可查看；`--pdf` 还会生成 `report.pdf`。输出目录名带源文件哈希前缀，便于区分同名的不同导出版本。

Windows 也可以把一个或多个文件拖到 `解析流程.cmd`。拖放默认生成 HTML、Markdown 和 JSON，输出在工具目录的 `reports` 下。启动器依次查找 `OA_WORKFLOW_PYTHON`、本目录 `.venv`、本机 Codex 附带的 Python，最后使用 `py -3`。按上述步骤安装后可直接拖放；需要指定环境时，在终端执行：

```powershell
$env:OA_WORKFLOW_PYTHON = (Resolve-Path '.\.venv\Scripts\python.exe').Path
& '.\解析流程.cmd' 'D:\example-documents\Downloads\采购在途订单取消流程 (1).wewf' --pdf
```

`OA_WORKFLOW_PYTHON` 应填写 Python 可执行文件路径，不包含命令参数；上面的设置只影响当前终端及其启动的程序。拖放启动的控制台可能在完成后关闭，结果仍保留在 `reports` 目录。需要保留运行摘要时优先使用上述终端命令。

## 批量解析

多个文件可以在一次命令中提供：

```powershell
.\.venv\Scripts\python.exe .\run.py 'D:\OA导出\流程甲.wewf' 'D:\OA导出\流程乙.wewf' --output 'D:\OA说明书'
```

输入文件夹时默认只扫描该层；加 `--recursive` 才递归扫描子文件夹：

```powershell
.\.venv\Scripts\python.exe .\run.py 'D:\OA导出' --recursive --output 'D:\OA说明书' --pdf
```

输入支持 `.wewf` 或原始流程 `.xml`，路径支持中文和空格。文件夹扫描也会发现 `.exml`，但当前版本会把加密 EXML 明确列为失败，不能将其改扩展名后当作已解密文件。一个文件失败不会中断其他文件；摘要中的 `failed` 大于零时，退出码为 `1`。参数用法错误由命令行解析器返回退出码 `2`。CLI 标准输出使用 UTF-8 JSON，程序调用时也应按 UTF-8 解码。

常用参数：

| 参数 | 作用 |
| --- | --- |
| `--output DIR` | 输出根目录；直接运行时默认是当前工作目录下的 `reports` |
| `--recursive` | 递归扫描输入文件夹 |
| `--pdf` | 同时生成 PDF，需要 PDF 附加依赖 |
| `--language 7` | 优先使用语言 ID `7` 的标签，默认简体中文；更换 ID 不会翻译原文 |
| `--version` | 显示工具版本 |

安装本包后，也可以用同一环境里的命令入口，参数完全相同：

```powershell
.\.venv\Scripts\oa-workflow.exe 'D:\OA导出' --output 'D:\OA说明书'
```

## 输出文件怎么看

| 文件 | 用途 |
| --- | --- |
| `report.html` | 日常阅读的离线流程说明书，自包含且不执行源脚本 |
| `report.md` | 便于版本比较、复制和继续编辑的说明书 |
| `report.pdf` | 使用 `--pdf` 时生成的打印版本 |
| `workflow.json` | 完整标准结果：流程、字段、权限、规则、脚本线索、证据及缺口 |
| `evidence.json` | 原始配置记录索引和导出表清单，通过证据 ID 查原值及 XML 行号 |
| `missing-data.json` | 尚不能还原的内容、原因、所需资料及建议的只读采集方式 |
| `agent-context.json` | 智能体入口，包含分析结果、信任边界和配套文件位置 |
| `manifest.json` | 源文件、分析结果和输出文件的哈希及版本，用于验证结果复用 |

建议先读 `report.html`，再看 `missing-data.json`，需要核对具体结论时按 `source_refs` 查询 `evidence.json`。结构约定见 [JSON Schema](src/oa_workflow_analyzer/schemas/workflow.schema.json)，智能体接入见 [AGENT_GUIDE.md](AGENT_GUIDE.md)。

重复解析相同内容时，工具仍会读取并分析输入，再检查已有结果。只有工具版本、分析内容、完整文件集合以及每个文件的大小和哈希均匹配，才复用输出并返回 `cached: true`。源文件或分析结果不同会生成相应的新结果；已有报告被编辑、目录多了其他文件或缓存不完整时，CLI 会选择带 `-2` 等后缀的新目录，保留旧目录。

不要依赖修改 `manifest.json` 来更新报告。需要保留人工补充时，可以另存副本；需要重新生成时再次运行即可。Python 的 `write_analysis` 使用调用者指定的独立目录，遇到被修改或被占用的目录会抛出 `OutputError`，不会自动选择后缀目录。

## 解析范围与结论边界

当前结果覆盖流程和表单基本信息、节点及连线、字段与选项、节点字段权限、明细行权限、操作人规则、会签及抄送配置、公式、属性联动、数据带入、节点动作、编号、撤回配置，以及布局中可识别的字段位置和隐藏状态。多个流程、不同节点数和字段数采用同一套结构，不按本次采购流程的 ID 或数量写死。

布局脚本只做离线解码和静态分析：列出事件、命名函数调用、请求地址、字段写入及条件线索。静态调用链不能证明分支一定执行、请求一定成功或后台实现符合脚本的假设。动态函数、复杂 JavaScript 或未知编码会保留为待核对事项。

已核验的配置含义由结果中的 `analyzer.profile` 标识。未知枚举保留原值，并产生缺口；其他 OA 版本的同名字段不保证含义相同。字段的默认权限、模板行列隐藏、禁止手工编辑和动态修改线索分别记录，不能只凭一项配置推断运行时最终可见或可编辑状态。未导出某表与导出了一张空表也会区分。

`summary.status` 为 `partial` 表示有当前尚不能解释的内容；`parsed` 表示没有触发此类缺口。两者都只表示离线解析情况，均不代表线上流程验证通过。`analyzer.runtime_verified` 始终为 `false`。原始导出包、完整人员档案和许可证内容不会复制到结果包；工具会尽量遮蔽明显凭据，但结果仍可能包含业务配置和少量必要的人员标识，应按原流程资料的访问范围保存。

输入有大小限制：文件最大 64 MiB、流程 XML 最大 32 MiB、压缩包最多 256 个条目、声明解压总量最大 128 MiB，压缩率也有检查。包含多个 XML 的压缩包会拒绝解析，避免错误合并。输入损坏、DTD、实体声明、危险压缩路径或不支持的加密格式会明确报错。

## 文件外的资料怎么补

具体以每次生成的 `missing-data.json` 为准。常见需要补充的内容如下：

| 缺少的证据 | 可补充的资料 |
| --- | --- |
| 自定义接口或 Action | 注册项、节点及执行时机、实现源码、服务器实际加载类或 JAR 的版本与哈希 |
| 自定义浏览框、数据带入 | 浏览定义、查询 SQL、返回字段、数据源类型、启用状态及去敏样例；不要提供连接密码 |
| 实际取人和权限 | 当前角色成员、组织范围、人员状态及具体请求的取人日志 |
| 业务执行结果 | 有授权的历史 `requestid`、审批日志、接口回执及相应外部系统单据 |
| 布局或附件引用 | 对应文件、相对路径及版本哈希 |
| 未识别的编码或规则 | OA 版本、对应后台配置截图或只读导出、有关实现代码 |

解析不需要调用 `getImportInfo`。该接口可能启动导入和配置写入，不能把它当作只读查询入口。补证时应读取配置、源码和历史日志，不通过重新提交业务流程验证推测。

如需进一步分析在途积压、退回转办、会签等待及优化方向，接口数据需求见 [运行分析接口约定](RUNTIME_API_CONTRACT.md)。首版在现有 V_JDSX 外补充实例清单和操作日志；完整人员记录可作为明细模式。该文档为接入设计，当前解析器尚未实现运行数据采集与分析。

## Python API

安装到所用 Python 环境后：

```python
from oa_workflow_analyzer import analyze_export, write_analysis

result = analyze_export(
    r"D:\example-documents\Downloads\采购在途订单取消流程 (1).wewf",
    language="7",
)
print(result["summary"])
for gap in result["gaps"]:
    print(gap["id"], gap["title"], gap["needed"])

# 使用不存在或空的独立目录；pdf=True 需要 PDF 附加依赖。
written = write_analysis(result, r"D:\OA说明书\单次API结果", pdf=False)
print(written["output_dir"], written["cached"])
```

`analyze_export` 返回字典，不写结果文件，也不调用业务系统。单文件调用遇到不支持或损坏的输入时抛出异常，批量隔离失败由 CLI 负责。调用者可读取异常的 `code` 属性；没有该属性时应保留异常类型和错误文本，不能转换成空的成功结果。

## 维护和验证

在工具目录运行自建样例测试：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[pdf,test]"
$env:PYTHONPATH = (Resolve-Path '.\src').Path
$env:PYTHONIOENCODING = 'utf-8'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

`test` 附加依赖用于实际验证 JSON Schema；未安装 `jsonschema` 时，对应验证测试会明确跳过。

需要验证本地真实导出时可额外设置 `OA_WORKFLOW_SAMPLE`，该文件不会成为普通测试的必需输入：

```powershell
$env:OA_WORKFLOW_SAMPLE = 'D:\example-documents\Downloads\采购在途订单取消流程 (1).wewf'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

增加平台版本或表结构适配时，应先保留可复现的去敏样例与证据，再调整解释配置档案及回归测试。不要提交原始流程包、业务凭据或人员资料。
