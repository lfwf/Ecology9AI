# 新增OA表的数据字典导出

## 两层来源

完整字典合并SQL Server实际物理结构与OA配置中文语义。前者来自系统目录，后者来自表单、模块、流程、标签和选择项配置。数据库没有MS_Description时仍可能从OA配置恢复中文含义；OA声明类型不能覆盖实际列类型。初始静态字典只作参考，不代表后来新增的对象。

本skill附带三个只读脚本：

- [00_discover.sql](../scripts/dictionary/00_discover.sql)：记录数据库/版本/导出时间及可见OA配置表列，3个结果集。
- [01_physical_metadata.sql](../scripts/dictionary/01_physical_metadata.sql)：导出可见用户表、视图、字段、键、索引、外键、扩展属性和检查约束，8个结果集。
- [02_generate_oa_queries.sql](../scripts/dictionary/02_generate_oa_queries.sql)：按当前可见表列生成白名单配置SELECT文本，1个结果集；不执行生成的SQL。

开发副本SQL位于工具根目录dictionary，分享包位于skill的scripts/dictionary。没有数据库权限时交给用户/DBA运行，或让其封装为已有只读接口；不尝试直连、不自行取得权限、不执行写库或业务调用。所有脚本均须按实际数据库版本和授权范围核对，本skill不宣称已经在用户库执行验证。

## 最短操作

1. 用户/DBA在SSMS选定实际OA库，使用获准账号，结果到网格。执行00，把三个网格分别保存manifest.csv、oa_visible_objects.csv、oa_visible_columns.csv。
2. 执行01，八个网格分别保存tables.csv、views.csv、columns.csv、keys.csv、indexes.csv、foreign_keys.csv、extended_properties.csv、check_constraints.csv。
3. 执行02，保存oa_query_plan.csv。先看generator_status、missing_required_columns、missing_optional_columns、can_select及schema歧义，再审阅并单独运行获准的非空generated_sql，每个结果保存为schema.配置表名.csv。

每个结果集单独CSV，不混成一个文件；含标题、中文编码及完整长文本。空结果保留标题并注明已执行，未执行或无权限分别记录，不能伪造成已查到为空。可在SSMS中每次选中完整SELECT或WITH...SELECT块执行，只导一张网格。版本、范围、时间及错误随文件保留。无需提供连接密码或员工考勤记录。

02按实际schema与列名生成查询；缺必要列不生成，缺可选列投影NULL并列出缺项。查询文本不是执行结果，不能将其当成已获取字段字典。多schema同名对象由用户/DBA确认正确来源。

## 合并关系

- 实际对象以database/schema/object/column为键。OA表名未带schema时，先在物理清单中匹配；多候选标歧义，不任选dbo。
- 新式表单：workflow_bill.id关联workflow_billfield.billid；主表名来自workflow_bill.tablename，明细结合detailtable与workflow_billdetailtable核对。未证明时不一律假设明细键为mainid。
- 字段中文：fieldlabel关联htmllabelinfo.indexid；表单中文用namelabel关联，中文默认languageid=7。保留缺标签及冲突，htmllabelindex描述可列候选，不随机用MAX/TOP1覆盖。
- 模块：modeinfo.formid关联表单。流程：workflow_base先看isbill；旧式表单不能硬套新式字段链。一个表单可被多个流程和模块复用，保留全部关联及版本状态。
- 选择项按isbill、fieldid、selectvalue对应中文；保留0、取消和历史项。公共/级联选择项另带主明细及字段引用，公共条目ID不等于业务保存值。
- 实际长度保持max_length字节口径；nchar/nvarchar可另列UTF-16代码单元数，varchar字节不等于通用字符数。保留精度、小数位、可空、默认值、自增、主键顺序和真实外键。
- browser.xxx及OA页面类型属于逻辑配置；部门/人员/选择框不等于数据库已声明外键。物理FK与OA逻辑关系列为不同栏目。

最少列出实际字段但未匹配OA、OA字段未匹配实际、类型不同、中文未取到、跨schema歧义及外部/虚拟对象未覆盖等差异。匹配失败不自动证明对象不存在；先看权限、范围、版本与快照时间。

## 可见范围及文档生成

SQL Server元数据受账号权限影响，未返回或NULL先标当前账号未取到，不能据此认定没有表、注释、约束或索引。元数据可见权限与配置表SELECT权限分开。脚本不包含授权语句，也不要求sysadmin。

拿到CSV后生成静态HTML目录及每表详情，或按用户需求生成Excel/Markdown。每表列出物理名称、中文与来源、模块/流程关联、主明细及状态；字段列出实际结构、OA逻辑类型、选项和差异。该结果用于说明，不能当成完整数据库备份或可直接重建的DDL。

若通过只读接口提供，按固定查询ID及对象白名单返回元数据与配置，保留采集时间、可见范围、分页完整性和错误。外部数据源及其他库另列依赖，不自行跨库连接。

参考：[SQL Server列元数据](https://learn.microsoft.com/en-us/sql/relational-databases/system-catalog-views/sys-columns-transact-sql)、[扩展属性](https://learn.microsoft.com/en-us/sql/relational-databases/system-catalog-views/extended-properties-catalog-views-sys-extended-properties)、[元数据可见性](https://learn.microsoft.com/en-us/sql/relational-databases/security/metadata-visibility-configuration)、[SSMS结果操作](https://learn.microsoft.com/en-us/ssms/quickstarts/work-with-query-results)。以实际执行版本及最新官方说明核对。
