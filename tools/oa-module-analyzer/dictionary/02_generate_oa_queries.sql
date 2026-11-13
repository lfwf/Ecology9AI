/*
Optional OA semantic/configuration export generator. Returns SQL text; does not execute it.
Run this SELECT first; it reads only sys catalog metadata and returns generated_sql text.
The user/DBA then chooses the correct schema, reviews the fixed column whitelist, and
runs each non-NULL generated SELECT separately, saving <schema>.<metadata_table>.csv.

Adaptation: references exact visible object/column names; missing optional columns are
projected as NULL and explicitly listed. Missing required columns stop query generation.
No EXEC, dynamic execution, SELECT *, DDL, DML, business-table samples, or credentials.
The generated SELECTs read ONLY the named OA configuration/label/choice tables below.
The column lists are based on the supplied dictionary and local JSP evidence, not a live DB.
*/

;WITH TableSpecs AS
(
    SELECT table_name, columns_csv, required_csv, filter_column, filter_value
    FROM (VALUES
        (N'workflow_bill',
         N'id,namelabel,tablename,detailtablename,detailkeyfield,invalid,formdes,from_module_',
         N'id,tablename', N'', N''),
        (N'workflow_billfield',
         N'id,billid,fieldname,fieldlabel,fielddbtype,fieldhtmltype,type,viewtype,detailtable,dsporder,selectitem,selectitemtype,pubchoiceid,pubchilchoiceid,linkfield,childfieldid,qfws',
         N'id,billid,fieldname', N'', N''),
        (N'workflow_billdetailtable',
         N'id,billid,tablename,title,orderid',
         N'billid,tablename', N'', N''),
        (N'htmllabelinfo',
         N'indexid,labelname,languageid',
         N'indexid,labelname,languageid', N'languageid', N'7'),
        (N'htmllabelindex',
         N'id,indexdesc',
         N'id,indexdesc', N'', N''),
        (N'workflow_base',
         N'id,workflowname,formid,isbill,isvalid,version,activeversionid',
         N'id,formid,isbill', N'', N''),
        (N'modeinfo',
         N'id,modename,modedesc,formid,isdelete',
         N'id,formid', N'', N''),
        (N'workflow_selectitem',
         N'id,fieldid,isbill,selectvalue,selectname,listorder,isdefault,childitemid,cancel,pubid',
         N'fieldid,isbill,selectvalue,selectname', N'', N''),
        (N'mode_selectitempage',
         N'id,selectitemname,selectitemdesc,formids',
         N'id', N'', N''),
        (N'mode_selectitempagedetail',
         N'id,mainid,name,disorder,defaultvalue,pid,statelev,cancel,name1,name2',
         N'id,mainid', N'', N''),
        (N'modeformextend',
         N'formid,appid,isvirtualform,virtualformtype,vdatasource,vprimarykey,vpkgentype',
         N'formid', N'', N''),
        (N'modeformfieldextend',
         N'formid,fieldid,needlog,needexcel,impcheck,placeholder',
         N'formid,fieldid', N'', N''),
        (N'workflow_formbase',
         N'id,formname,formdesc',
         N'id', N'', N''),
        (N'workflow_formfield',
         N'formid,fieldid,isdetail,groupid,fieldorder',
         N'formid,fieldid', N'', N''),
        (N'workflow_formdict',
         N'id,fieldname,fielddbtype,fieldhtmltype,type,description,childfieldid,qfws',
         N'id,fieldname', N'', N''),
        (N'workflow_formdictdetail',
         N'id,fieldname,fielddbtype,fieldhtmltype,type,description,childfieldid,qfws',
         N'id,fieldname', N'', N''),
        (N'workflow_fieldlable',
         N'formid,fieldid,fieldlable,langurageid,isdefault',
         N'formid,fieldid,fieldlable,langurageid', N'langurageid', N'7')
    ) AS specs(table_name, columns_csv, required_csv, filter_column, filter_value)
),
ColumnNames AS
(
    SELECT ts.table_name,
           fields.node.value(N'text()[1]', N'nvarchar(128)') AS column_name,
           ts.required_csv
    FROM TableSpecs AS ts
    CROSS APPLY
    (
        SELECT CONVERT(xml, N'<c>' + REPLACE(ts.columns_csv, N',', N'</c><c>') + N'</c>') AS column_xml
    ) AS parsed
    CROSS APPLY parsed.column_xml.nodes(N'/c') AS fields(node)
),
ColumnSpecs AS
(
    SELECT table_name, column_name,
           CASE WHEN CHARINDEX(N',' + column_name + N',', N',' + required_csv + N',') > 0
                THEN 1 ELSE 0 END AS is_required
    FROM ColumnNames
),
Matches AS
(
    SELECT ts.table_name AS expected_table_name, ts.filter_column, ts.filter_value,
           o.object_id, o.name AS actual_table_name, s.name AS schema_name,
           COUNT(o.object_id) OVER (PARTITION BY ts.table_name) AS visible_name_matches
    FROM TableSpecs AS ts
    LEFT JOIN sys.objects AS o
        ON LOWER(o.name) = ts.table_name AND o.type IN (N'U', N'V') AND o.is_ms_shipped = 0
    LEFT JOIN sys.schemas AS s ON s.schema_id = o.schema_id
)
SELECT
    DB_NAME() AS database_name,
    m.expected_table_name,
    m.schema_name,
    m.actual_table_name,
    m.visible_name_matches,
    HAS_PERMS_BY_NAME(QUOTENAME(m.schema_name) + N'.' + QUOTENAME(m.actual_table_name), N'OBJECT', N'SELECT') AS can_select,
    CASE WHEN m.object_id IS NULL THEN N'NOT_VISIBLE_OR_NOT_PRESENT'
         WHEN missing.required_columns IS NOT NULL THEN N'REQUIRED_COLUMNS_NOT_VISIBLE'
         WHEN m.visible_name_matches > 1 THEN N'READY_REQUIRES_SCHEMA_CHOICE'
         ELSE N'READY_FOR_REVIEW' END AS generator_status,
    missing.required_columns AS missing_required_columns,
    missing.optional_columns AS missing_optional_columns,
    CASE WHEN m.object_id IS NULL OR missing.required_columns IS NOT NULL THEN NULL
         ELSE CAST(N'SELECT ' AS nvarchar(max)) + projected.column_list
              + N' FROM ' + QUOTENAME(m.schema_name) + N'.' + QUOTENAME(m.actual_table_name) + N' AS q'
              + CASE WHEN filter_c.column_id IS NOT NULL
                     THEN N' WHERE q.' + QUOTENAME(filter_c.name) + N' = ' + m.filter_value
                     ELSE N'' END + N';'
    END AS generated_sql
FROM Matches AS m
LEFT JOIN sys.columns AS filter_c
    ON filter_c.object_id = m.object_id AND LOWER(filter_c.name) = m.filter_column AND m.filter_column <> N''
OUTER APPLY
(
    SELECT
        STUFF((
            SELECT N',' + cs.column_name
            FROM ColumnSpecs AS cs
            LEFT JOIN sys.columns AS c ON c.object_id = m.object_id AND LOWER(c.name) = cs.column_name
            WHERE cs.table_name = m.expected_table_name AND cs.is_required = 1 AND c.column_id IS NULL
            ORDER BY cs.column_name
            FOR XML PATH(N''), TYPE
        ).value(N'.', N'nvarchar(max)'), 1, 1, N'') AS required_columns,
        STUFF((
            SELECT N',' + cs.column_name
            FROM ColumnSpecs AS cs
            LEFT JOIN sys.columns AS c ON c.object_id = m.object_id AND LOWER(c.name) = cs.column_name
            WHERE cs.table_name = m.expected_table_name AND cs.is_required = 0 AND c.column_id IS NULL
            ORDER BY cs.column_name
            FOR XML PATH(N''), TYPE
        ).value(N'.', N'nvarchar(max)'), 1, 1, N'') AS optional_columns
) AS missing
OUTER APPLY
(
    SELECT STUFF((
        SELECT N', ' + CASE WHEN c.column_id IS NULL
                           THEN N'CAST(NULL AS nvarchar(4000))'
                           ELSE N'q.' + QUOTENAME(c.name) END
                    + N' AS ' + QUOTENAME(cs.column_name)
        FROM ColumnSpecs AS cs
        LEFT JOIN sys.columns AS c ON c.object_id = m.object_id AND LOWER(c.name) = cs.column_name
        WHERE cs.table_name = m.expected_table_name
        ORDER BY COALESCE(c.column_id, 2147483647), cs.column_name
        FOR XML PATH(N''), TYPE
    ).value(N'.', N'nvarchar(max)'), 1, 2, N'') AS column_list
) AS projected
ORDER BY m.expected_table_name, m.schema_name;
