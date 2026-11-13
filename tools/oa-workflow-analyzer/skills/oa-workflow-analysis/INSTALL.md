# 安装与使用

这是可分享的 `oa-workflow-analysis` skill，附带离线流程解析器源码。Python及第三方依赖不包含在压缩包内；不需要连接数据库或登录OA。基础解析不需要密钥、账号或公司网络。

当前skill版本为1.2.1，包含《OA流程质量审查清单v2.0》及辅助分析方法。清单帮助查漏补缺，相关发现融入同一份流程说明书，无关项跳过；默认不生成逐项状态表或独立审查报告。分发容器小于3,000,000字节，公开清单原文保留在 `references`，企业报告和证据不在包中。

## 安装skill

解压ZIP，将整个 `oa-workflow-analysis` 文件夹放入个人技能目录。Windows本机使用的目录为 `%USERPROFILE%\.agents\skills`；也可使用目标Codex环境已配置的技能目录。最终应能找到 `oa-workflow-analysis/SKILL.md`，不要多套一层同名目录。刷新技能列表或新开会话后使用。

同版本的 `.zip` 和 `.skill` 是内容相同的ZIP容器，任选一份。使用 `.skill` 前应确认目标工具支持这种文件扩展名；需要手动解压时使用 `.zip`。本包未验证其他产品的技能导入能力。

## 准备Python依赖

需要Python 3.10或更高版本。若已有包含 `lxml`、`cryptography` 的解释器，可直接运行内置工具；需要基础PDF时还需 `reportlab`。创建独立环境的Windows PowerShell示例，先替换技能目录：

```powershell
$skillDir = 'C:\技能目录\oa-workflow-analysis'
Set-Location (Join-Path $skillDir 'scripts\analyzer')
py -3 -m venv .venv
& '.\.venv\Scripts\python.exe' -m pip install -e '.[pdf]'
& '.\.venv\Scripts\python.exe' '.\run.py' --version
```

macOS或Linux可在同一工具目录使用 `python3 -m venv .venv`，然后用 `.venv/bin/python -m pip install -e '.[pdf]'`。本次打包在Windows验证；其他系统未实机验证。依赖安装可能访问所配置的软件包源，流程解析本身不会上传流程内容。不要将 `.venv` 再打包分享。

## 调用

向智能体提供自己的流程导出文件并说：

```text
使用 $oa-workflow-analysis 分析这个 .wewf 文件，参考质量清单查漏补缺，
把有关的问题、影响和优化方向整合到分析结论，无关项跳过，
最终给我一份中文流程说明书。
```

也可只生成解析器基础报告：

```powershell
& '.\.venv\Scripts\python.exe' '.\run.py' 'C:\OA导出\示例流程.wewf' --output 'C:\OA说明书' --pdf
```

基础报告是配置和证据呈现；完整中文业务说明和优化结论由skill指导智能体进一步整理。命令本身不会自动完成业务判断，也不会采集运行数据。Skill优先使用用户指定工具或 `OA_WORKFLOW_ANALYZER_HOME`，未指定时使用本包的 `scripts/analyzer`；通常无需设置环境变量。

## 内容与适用范围

包含流程／表单／路径／权限／取人／公式／脚本静态分析工具、证据结构、中文分析方法及公开质量清单。技能指导智能体还原说明书并完善分析，不是逐项审计或自动放行程序。不包含公司真实流程包、分析报告、人员记录、账号凭据、虚拟环境或第三方二进制依赖。`package-manifest.json`记录内置文件的大小和SHA-256，可核对完整性，不是来源认证或数字签名。

未知OA版本、平台代码、外部接口和实际部署须按证据核对。`.exml`加密格式当前不支持。运行耗时、积压和卡点频率需要另行授权提供运行数据；本包没有数据库连接器、API采集器或已实现的运行分析服务。
