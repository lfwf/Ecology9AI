/*
SQL Server dictionary discovery. Run in the intended OA database, by the user/DBA.
Read-only: SELECT/CTE only; no business-table data is read.
An absent catalog row means NOT VISIBLE to this principal, not proven nonexistent.
Save each result set separately, retaining headers and Unicode.
*/

-- Result 1: manifest.csv
SELECT
    DB_NAME() AS database_name,
    CONVERT(nvarchar(128), SERVERPROPERTY(N'ProductVersion')) AS product_version,
    CONVERT(nvarchar(128), SERVERPROPERTY(N'Edition')) AS edition,
    CONVERT(nvarchar(128), DATABASEPROPERTYEX(DB_NAME(), N'Collation')) AS database_collation,
    USER_NAME() AS database_principal,
    CONVERT(nvarchar(33), SYSUTCDATETIME(), 126) AS exported_at_utc,
    HAS_PERMS_BY_NAME(DB_NAME(), N'DATABASE', N'VIEW DEFINITION') AS database_view_definition,
    N'Current-principal-visible metadata only; NULL/0 permission results do not prove object absence.' AS visibility_note;

-- Result 2: oa_visible_objects.csv
;WITH ExpectedNames AS
(
    SELECT name FROM (VALUES
        (N'workflow_bill'), (N'workflow_billfield'), (N'workflow_billdetailtable'),
        (N'htmllabelinfo'), (N'htmllabelindex'), (N'workflow_base'),
        (N'modeinfo'), (N'workflow_selectitem'),
        (N'mode_selectitempage'), (N'mode_selectitempagedetail'),
        (N'modeformextend'), (N'modeformfieldextend'),
        (N'workflow_formbase'), (N'workflow_formfield'),
        (N'workflow_formdict'), (N'workflow_formdictdetail'), (N'workflow_fieldlable')
    ) AS names(name)
)
SELECT
    e.name AS expected_name,
    s.name AS schema_name,
    o.name AS actual_name,
    o.type_desc AS object_type,
    o.object_id,
    COUNT(o.object_id) OVER (PARTITION BY e.name) AS visible_name_matches,
    CASE WHEN o.object_id IS NULL THEN N'NOT_VISIBLE_OR_NOT_PRESENT'
         ELSE N'VISIBLE' END AS discovery_status,
    HAS_PERMS_BY_NAME(QUOTENAME(s.name) + N'.' + QUOTENAME(o.name), N'OBJECT', N'SELECT') AS can_select,
    HAS_PERMS_BY_NAME(QUOTENAME(s.name) + N'.' + QUOTENAME(o.name), N'OBJECT', N'VIEW DEFINITION') AS object_view_definition
FROM ExpectedNames AS e
LEFT JOIN sys.objects AS o
    ON LOWER(o.name) = e.name AND o.type IN (N'U', N'V') AND o.is_ms_shipped = 0
LEFT JOIN sys.schemas AS s ON s.schema_id = o.schema_id
ORDER BY e.name, s.name;

-- Result 3: oa_visible_columns.csv. Actual names/types, including version-specific extra columns.
SELECT
    s.name AS schema_name,
    o.name AS object_name,
    o.type_desc AS object_type,
    c.column_id,
    c.name AS column_name,
    ty.name AS declared_type,
    TYPE_NAME(c.system_type_id) AS system_type,
    c.max_length AS max_length_bytes,
    c.precision,
    c.scale,
    c.is_nullable
FROM sys.objects AS o
JOIN sys.schemas AS s ON s.schema_id = o.schema_id
JOIN sys.columns AS c ON c.object_id = o.object_id
JOIN sys.types AS ty ON ty.user_type_id = c.user_type_id
WHERE o.is_ms_shipped = 0 AND o.type IN (N'U', N'V')
  AND LOWER(o.name) IN
  (
      N'workflow_bill', N'workflow_billfield', N'workflow_billdetailtable',
      N'htmllabelinfo', N'htmllabelindex', N'workflow_base',
      N'modeinfo', N'workflow_selectitem', N'mode_selectitempage',
      N'mode_selectitempagedetail', N'modeformextend', N'modeformfieldextend',
      N'workflow_formbase', N'workflow_formfield', N'workflow_formdict',
      N'workflow_formdictdetail', N'workflow_fieldlable'
  )
ORDER BY s.name, o.name, c.column_id;
