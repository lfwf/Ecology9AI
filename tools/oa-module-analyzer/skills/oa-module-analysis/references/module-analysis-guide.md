# 模块分析要点

## 文件及证据

常见包由data.xml、config/config.xml、browser.xml、froeignData.xml（原拼写）、modifyInfo.xml、workFlowSet.xml、dataForm.xml、dataSetForm.xml及file.xml组成。不同导出版本可增减成员；按当前包识别，不因名字相似就合并值。

- data.xml通常包含模块、表单、字段、标签、选项、模板、列表、权限和扩展配置。
- config/config.xml是导出选择及版本信息，不表示其空标签在系统中没有配置。
- froeignData.xml可仅含外部对象ID/UUID引用，不是对象完整定义；依赖缺失要准确描述。
- modifyInfo.xml保留修改/迁移信息。没有导入器语义证据时，不把它直接覆盖主配置或拼成重复业务字段。
- dataForm.xml没有记录时，只能确认本包不含该业务记录；不查询数据库就不能判断实际台账为空。

每个重要判断应能定位到源文件哈希、ZIP成员、区段、记录及原XML行；解码内容再给字段名、文本行或JSON路径。取证数据不改写原包。

## 结构化结果的定向读取

`module.json.records`是以记录ID为键的对象，不是数组；原值位于每条记录的`values`，解码结果位于`decoded`。`normalized.fields/layouts/select_options`提供概览，`normalized.categories`指向记录ID；相同表在不同成员出现时要同时看`source_role`。`evidence.json.items`按证据ID索引位置。

先读少量概览，再按表过滤，例如：

```python
import json
from pathlib import Path
folder = Path('解析目录的绝对路径')
data = json.loads((folder / 'module.json').read_text(encoding='utf-8'))
proof = json.loads((folder / 'evidence.json').read_text(encoding='utf-8'))['items']
print(data['normalized']['identity'])
for field in data['normalized']['fields']:
    print(field['label'], field['name'], field['db_type'], proof[field['evidence']])
for rid, record in data['records'].items():
    if record['table'] == 'mode_databatchimport' and record['source_role'] == 'export_values':
        print(rid, record['values'], proof[record['evidence']])
```

布局JSON解码成功时，结构保存在`decoded['datajson']['value']`且`format`为`json`；先检查状态及类型，再按模板、字段或事件截取。未知编码保留错误，不要将整段编码和完整表数据打印进上下文。

## 先回答业务问题

谁生成数据、从哪里来？按人/月份/组织等什么粒度记录？谁能查询、改动、共享、删除和导出？哪些数据由自动带出、导入校验或程序计算保障？什么时候可供下游使用，怎样纠错和追溯？字段及模块中文名只能帮助理解，不能替代这些证据。

## 易错语义

| 对象 | 应核对什么 |
| --- | --- |
| 中文标签 | workflow_billfield.fieldlabel及workflow_bill.namelabel关联标签表，按语言区分；部分包标签值为Base64 UTF-8，保留原值和解码来源，不盲解全部字符串 |
| 字段及类型 | 主表与明细、OA逻辑类型、声明数据库类型、浏览框、自定义选择页分别记录；browser.xxx可能是逻辑类型而非SQL Server实际列类型 |
| 布局 | modehtmllayout与工作流布局枚举不同；用本版本页面/定义核对创建、显示、编辑类型，不仅凭数字或模板名称。默认、活动、用途分别判断 |
| 权限 | 模块创建权、已有记录权限、列表共享、按钮可见、列表编辑和模板列权限共同影响结果；授权项存在不证明所有人有效可见 |
| 按钮 | mode_pageexpand的系统按钮记录、defaultenable/isshow、列表mode_batchset的isuse、共享规则和记录权限分别核对；系统预置按钮不等于全部启用 |
| 字段控制 | 可见、允许编辑、必填、禁止手改、模板未布置、隐藏行列、条件联动和自动赋值不混为一项；自动带出后必填兜底是合理控制模式 |
| 列表 | 显示列与查询列、快速搜索、默认条件、系统列、modifyInfo中的修改信息分别计数，不能把42列直接当作42业务字段 |
| 导入 | 导入入口、校验器注册/开关、字段映射、模板列、唯一键、重复处理、错误行策略和实际类版本分别确认 |
| 外部依赖 | 自定义浏览框查询、角色、选择页、关联表、Java类及资源是否完整导出；缺定义不等于错误或无功能 |
| 数据字典 | OA声明类型和真实sys.columns类型分别标注；逻辑字段关联不等于已声明物理外键 |

## 公式、程序和风险

普通Base64 JSON布局只解码，不渲染执行源HTML。加密或未知编码保留原文和错误；不能用猜测的模板替代。公式的表达式、实际读取项、触发条件及适用模板分别核对；没有公式不等于没有后台计算。

有明确编码标记时才采用对应解码；未标记但形似Base64的值保留原值，候选解释不能直接变成确认名称。当前解析器仅对datatype=mode、cversion=9.00.2404.02且元数据无冲突的包应用已核模板类型：显示0、新建1、编辑2。依据为本地平台快照formmode/setup/ModeShareAdd.jsp第1724–1742行和FormModeHtmlBrowserIframe.jsp第94–103行，原文件哈希保存在type_interpretation.sources；分享包不含企业平台源码。其他版本保留未知与候选，须补当前版本证据后解释。

按类名或端点定向关联已授权的本地实现，保留哈希和方法/行号。若是未提交或开发中的文件，明确其版本范围。禁止为了验证猜测而运行导入、更新、删除或接口。返回空串/布尔值是否代表通过，需要接口契约或调用实现支持。

先提出对业务结果有实际影响的问题，例如责任归属不清、数据粒度与唯一键不一致、入口之间校验差异、共享/导出范围不明、公式依赖未覆盖、异常恢复缺口。已确认不一致给具体改法；依赖平台、业务制度或部署的问题，列核实条件及确认后的处理，不一概定为漏洞。

建议验收场景是方案，不是已执行结果。静态资料可发现配置一致性问题，不能量化实际积压、错算频率或个人效率。对每项重要发现合并现状依据、可能影响、优化动作和必要验证；不凑固定条数。

## 文档与复核

按实际内容组织模块用途、数据来源与依赖、用户角色、列表/查询、表单维护、导入导出、权限、计算/联动、运行边界、全部中文业务字段和已导出选项。没有的功能不扩充风险章节。

最终核对字段/模板/列表/操作覆盖及源引用有效性。保留人工说明书与解析输出的边界；不把工具生成的表清单当成完整业务说明。底稿可保留内部标识；业务稿使用中文并在同本文档附录说明来源。
