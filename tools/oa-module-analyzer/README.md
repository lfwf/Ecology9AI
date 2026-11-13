# OA建模模块离线解析

解析泛微E9表单建模导出ZIP，保留来源、原值、中文标签、布局、字段、权限和外部引用，辅助形成一份中文模块说明书。它不连接数据库、不导入模块，也不运行包内脚本或SQL。

## 使用

需要Python 3.10+及lxml；安装依赖可使用 `python -m pip install lxml`。

```powershell
$env:PYTHONUTF8='1'
python analyze_module.py 'D:\OA导出\模块.zip' --output 'D:\OA分析\模块结果'
```

输出module.json、evidence.json、table-inventory.json和manifest.json。manifest保留输入、成员和输出哈希；module.json.records按记录ID索引，normalized提供概览，evidence.json.items按证据ID定位。不会把外部引用和修改信息合并成正式配置。

未标记的Base64形状文本保留原值与候选；未知版本的模板类型保留未知与候选。当前已核枚举的适用版本及本地来源指纹保存在type_interpretation中，不把一种导出版本的解释扩展到其他版本。可选加密布局依赖见pyproject.toml；无法解码时保留状态，不猜测内容。

## 模块说明和技能

技能源在[skills/oa-module-analysis](skills/oa-module-analysis/SKILL.md)，开发副本优先复用本工具脚本。包内自带解析脚本、依赖声明和三份通用只读SQL，不带企业模块、源码、人员资料或分析报告。

```powershell
python -m unittest discover -s tests -v
python package_skill.py
```

分发包生成到dist，ZIP和.skill为同一内容；显式白名单、内部SHA-256清单、固定ZIP时间戳，小于3,000,000字节。相同源文件产生相同包。安装时将ZIP中oa-module-analysis目录放入用户技能目录，不要只复制SKILL.md。


## 新增表数据字典

见[字典导出使用说明](dictionary/README.md)。实际SQL Server结构与OA中文标签/选项要分别导出再合并；初始静态字典和模块包都不能替代当前数据库元数据。三份SQL供用户或DBA审阅执行，本工具没有运行它们。
