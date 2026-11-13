# 泛微 OA 数据字典导出指南（SQL Server）

用当前数据库的实际结构，加上 OA 的表单、字段、中文标签和选择项配置，可以整理出与初始 HTML 字典相似的新字典。初始字典不会自动包含后来新增的流程表单和建模表；新增字段也不一定带有数据库中文注释。

本目录提供只读导出 SQL 和操作方法。**尚未连接用户数据库、执行这些 SQL 或取得实际导出结果**，因此当前交付不是现网新增表的成品字典。方案依据本地初始字典、OA JSP 实现和 Microsoft 官方文档整理，实际版本、权限及导出结果需由用户或 DBA 核实。

## 1. 导出文件与读取范围

| SQL | 作用 | 结果集 |
| --- | --- | --- |
| [00_discover.sql](00_discover.sql) | 记录数据库/版本/执行账号的元数据可见性，发现实际可见的 OA 配置对象和列 | 3个 |
| [01_physical_metadata.sql](01_physical_metadata.sql) | 导出表、视图、字段、主键/唯一键、索引、外键、注释与检查约束 | 8个 |
| [02_generate_oa_queries.sql](02_generate_oa_queries.sql) | 按实际可见对象和列生成待审阅的 OA 配置 SELECT 文本 | 1个查询计划结果集 |

三个脚本直接读取的都是系统目录或元数据函数，没有写库、`EXEC`、临时表或业务表抽样。`02`仅生成 SQL 文本，不自动执行；用户或 DBA 另行运行获准的生成查询时，才会读取指定的 OA 配置、标签及选项记录。

`01`默认导出当前库**所有可见用户表和视图的元数据**，这样能保留自定义命名、非`dbo` schema 和本库虚拟视图。需要缩小时，对每个结果集使用同一份明确的 schema/对象白名单，并记录实际范围。只筛`formtable_main_%`或`uf_%`得到的是候选范围，不能据此保证完整覆盖。外部数据源、同义词和其他数据库不自动展开。

## 2. 最短操作步骤

全部操作由用户或 DBA 在获准环境中完成，无需向分析方提供连接密码或业务记录。

1. 在 SSMS 打开指向**实际 OA 数据库**的查询窗口，选择“结果到网格”（`Ctrl+D`）。
2. 执行`00_discover.sql`。每个结果集是一张独立网格，分别在对应网格内右键 **Save Results As / 将结果另存为**，选择CSV，按下表保存。
3. 执行`01_physical_metadata.sql`，把8张结果网格分别保存。若不便定位多个网格，每次选中一个完整的`SELECT...;`或`;WITH...SELECT...;`块，按F5执行，只保存这一张网格。**不要把多个结果集混在同一个CSV中，也不要将默认`.rpt`文件直接改名为CSV。**
4. 执行`02_generate_oa_queries.sql`，保存为`oa_query_plan.csv`。检查`generator_status`、`missing_required_columns`、`missing_optional_columns`、`visible_name_matches`和`can_select`。同名对象涉及多个schema时，由DBA先确认正确来源。
5. 对获准来源中`generated_sql`非NULL的行，复制完整的单条SELECT到新查询窗口，审阅后单独执行，保存为`<schema>.<expected_table_name>.csv`，例如`dbo.workflow_bill.csv`。复制时不要带上CSV外层的字符串引号。
6. 交付CSV及查询计划，注明导出时间、数据库版本、实际范围、未执行项及报错。空结果也保存带列标题的文件；没有执行或未获得结果的项，应注明“未执行/未取到”，不能伪造空CSV代表已查询为空。

保存CSV时包含列标题，保留中文编码，并确认长文本未被网格设置截断。较新SSMS保存窗口可选择包含标题；较早版本通常在“工具→选项→查询结果→SQL Server→结果到网格”设置。若旧查询窗口未采用新设置，重新打开窗口执行。[SSMS结果与导出说明](https://learn.microsoft.com/en-us/ssms/quickstarts/work-with-query-results)、[执行所选查询块的快捷键](https://learn.microsoft.com/en-us/ssms/sql-server-management-studio-keyboard-shortcuts)。

| 脚本/结果序号 | CSV文件名 |
| --- | --- |
| `00 / 1` | `manifest.csv` |
| `00 / 2` | `oa_visible_objects.csv` |
| `00 / 3` | `oa_visible_columns.csv` |
| `01 / 1` | `tables.csv` |
| `01 / 2` | `views.csv` |
| `01 / 3` | `columns.csv` |
| `01 / 4` | `keys.csv` |
| `01 / 5` | `indexes.csv` |
| `01 / 6` | `foreign_keys.csv` |
| `01 / 7` | `extended_properties.csv` |
| `01 / 8` | `check_constraints.csv` |
| `02` | `oa_query_plan.csv` |
| 每条获准的生成查询 | `<schema>.<expected_table_name>.csv` |

`02`使用实际可见的对象/列名称生成投影：必需列未取到时不生成查询；可选列未取到时投影为NULL，并列入`missing_optional_columns`。中文标签查询默认语言7，旧式表单语言列保留原拼写`langurageid`；其他语言由DBA修改生成查询中的固定语言值。

生成器的名单共17个配置对象，已按脚本核对：

| 配置类别 | 对象 |
| --- | --- |
| 表单与流程（4） | `workflow_bill`、`workflow_billfield`、`workflow_billdetailtable`、`workflow_base` |
| 标签（2） | `htmllabelinfo`、`htmllabelindex` |
| 建模及扩展（3） | `modeinfo`、`modeformextend`、`modeformfieldextend` |
| 普通/公共选择项（3） | `workflow_selectitem`、`mode_selectitempage`、`mode_selectitempagedetail` |
| 旧式表单（5） | `workflow_formbase`、`workflow_formfield`、`workflow_formdict`、`workflow_formdictdetail`、`workflow_fieldlable` |

## 3. 如何把实际结构与 OA 中文含义合并

先保留原始CSV，再按`数据库/schema/表/字段`建立字典键，生成静态HTML目录及每表详情，或Excel中的表清单、字段、枚举、关系和差异页。两层原始值和来源都应保留。

| 需要说明的内容 | 来源及合并方式 |
| --- | --- |
| 实际字段结构 | 以`columns.csv`及约束/索引结果为准，不能用OA配置中的类型覆盖实际DDL。初始字典中出现的`varchar2/number`也不能当作当前SQL Server类型 |
| 表单与主表 | `workflow_bill.id`对应表单，`tablename`指向主表；用`namelabel→htmllabelinfo.indexid`取得指定语言名称 |
| 字段与中文名 | `workflow_billfield.billid→workflow_bill.id`；`fieldlabel→htmllabelinfo.indexid`，中文默认`languageid=7` |
| 主明细 | `viewtype=0`关联主表；`viewtype=1`按`detailtable`匹配，并核对`workflow_billdetailtable`的表名/顺序。保留`detailtablename/detailkeyfield`，不假定所有明细都以`mainid`关联 |
| 建模归属 | `modeinfo.formid→workflow_bill.id`；一个表单可能供多个模块使用，保留全部归属和`isdelete`状态 |
| 流程归属 | `workflow_base.formid`须结合`isbill`解释；`isbill=1`走上述表单链，`isbill=0`走旧式表单配置，不混用字段ID和标签关联 |
| 选择项 | 按`(isbill,fieldid,selectvalue)`保留编码、中文、排序、默认及取消状态；值0和取消项也要保留，公共/级联选项另保留相关配置 |
| 外键与浏览框 | 数据库物理FK来自`foreign_keys.csv`；浏览框、主明细等OA应用关系另列“OA逻辑关联”，未经核实不当作数据库外键 |
| 虚拟表单 | 结合`modeformextend`说明本库表/视图或外部数据源；外部结构未导出时明确标记 |

合并时还要保留这些差异：

- **中文来源不同**：分别保留`MS_Description`、OA显示标签和原始标签ID。`htmllabelindex.indexdesc`只能作为标签描述候选；没有取得显示标签时不悄悄替代为已确认名称。相同标签ID出现不同文本时列出冲突。
- **配置与实际结构不一致**：分别列出物理字段未匹配配置、配置字段未匹配物理元数据、类型不同、标签未取到及虚拟/外部对象未覆盖，不能隐藏或直接判定不存在。
- **名称与范围不明确**：OA未带schema的表名若匹配多个实际对象，应列为歧义；保留数据库排序规则与原名。不以表单ID正负或常见表名前缀推断完整范围，保留历史/无效配置状态和表单复用关系。
- **长度单位不同**：`max_length_bytes`是字节数；`nvarchar/nchar`除以2对应声明的UTF-16代码单元数，不能对所有类型都除以2，或把`varchar`字节容量当作通用字符数。`-1`以及`text/ntext/image`需按类型解释。

每张表文档至少列出物理名称、中文名及来源、模块/流程/表单归属、主明细配置；每个字段列出实际类型、长度、精度、小数位、可空、自增、默认值、键、中文名、OA页面类型/浏览框代码、选择项和差异状态。

## 4. 权限、接口与核验边界

**当前账号未取到元数据，不等于数据库中不存在。** SQL Server目录视图、元数据函数和扩展属性受权限控制，可能返回部分行、空结果或NULL。`00`中的权限结果用于说明可见范围；数据库级`VIEW DEFINITION=0`也不代表对象级权限不可见。[Microsoft元数据可见性说明](https://learn.microsoft.com/en-us/sql/relational-databases/security/metadata-visibility-configuration)。

元数据查看权限和配置表SELECT权限分别核对。由用户或DBA使用已有获准账号，按内部授权确定必要范围；本包没有授权变更SQL，不要求提供业务表SELECT权限或使用`sysadmin`。

如使用既有只读接口，可将经审阅的查询固定为查询ID，限定配置对象名单，分别返回各结果集及列标题、数据库版本、执行时间、范围和错误。分页应完整返回并带结束标记或总数。本次没有新建、部署或调用OA接口。

脚本按SQL Server 2008以后已有语法编写，没有使用`STRING_AGG`或新版目录列。本地静态检查分别识别到3、8、1个SELECT/CTE，去掉注释和字符串后没有写库或动态执行语句，直接数据源仅系统目录与CTE。**尚未进行数据库引擎编译、实际权限或结果完整性验证。** 本包用于导出字典元数据，不是完整数据库备份或可原样重建数据库的DDL。

## 5. 官方参考

以下资料用于核对脚本的目录字段、关联及结果解释：

- [sys.schemas](https://learn.microsoft.com/en-us/sql/relational-databases/system-catalog-views/schemas-catalog-views-sys-schemas?view=sql-server-ver16)、[sys.tables](https://learn.microsoft.com/en-us/sql/relational-databases/system-catalog-views/sys-tables-transact-sql)、[sys.objects](https://learn.microsoft.com/en-us/sql/relational-databases/system-catalog-views/sys-objects-transact-sql?view=sql-server-ver16)：schema、用户表和对象标识。
- [sys.columns](https://learn.microsoft.com/en-us/sql/relational-databases/system-catalog-views/sys-columns-transact-sql)、[sys.types](https://learn.microsoft.com/en-us/sql/relational-databases/system-catalog-views/sys-types-transact-sql)：列结构、字节长度、声明类型及底层类型。
- [sys.default_constraints](https://learn.microsoft.com/en-us/sql/relational-databases/system-catalog-views/sys-default-constraints-transact-sql?view=sql-server-ver16)、[sys.identity_columns](https://learn.microsoft.com/en-us/sql/relational-databases/system-catalog-views/sys-identity-columns-transact-sql?view=sql-server-ver17)、[sys.computed_columns](https://learn.microsoft.com/en-us/sql/relational-databases/system-catalog-views/sys-computed-columns-transact-sql?view=sql-server-ver16)：默认、自增及计算列定义。
- [sys.key_constraints](https://learn.microsoft.com/en-gb/sql/relational-databases/system-catalog-views/sys-key-constraints-transact-sql?view=sql-server-ver16)、[sys.indexes](https://learn.microsoft.com/en-us/sql/relational-databases/system-catalog-views/sys-indexes-transact-sql?view=azuresqldb-current)、[sys.index_columns](https://learn.microsoft.com/en-us/sql/relational-databases/system-catalog-views/sys-index-columns-transact-sql?view=sql-server-ver16)：主键/唯一键、索引与列顺序；隐式附带的聚集键不一定列在索引列视图中。
- [sys.foreign_keys](https://learn.microsoft.com/en-us/sql/relational-databases/system-catalog-views/sys-foreign-keys-transact-sql?view=sql-server-ver16)、[sys.foreign_key_columns](https://learn.microsoft.com/en-us/sql/relational-databases/system-catalog-views/sys-foreign-key-columns-transact-sql?view=sql-server-ver17)：物理外键、复合列顺序及状态。
- [sys.extended_properties](https://learn.microsoft.com/en-us/sql/relational-databases/system-catalog-views/extended-properties-catalog-views-sys-extended-properties)、[sys.check_constraints](https://learn.microsoft.com/en-us/sql/relational-databases/system-catalog-views/sys-check-constraints-transact-sql?view=sql-server-2017)：对象/列/索引属性及检查表达式。
