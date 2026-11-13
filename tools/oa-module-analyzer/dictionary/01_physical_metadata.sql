/*
Physical dictionary, SQL Server 2008+ catalog syntax. Not executed against a database here.
SELECT only. Reads catalog metadata, never SELECTs form/HR/request business rows.
Default scope: ALL currently visible user tables/views, to retain custom names and schemas.
If a narrower scope is needed, the user/DBA should apply the SAME explicit schema/name
allowlist to each result set. Prefix-only filtering is not proof of complete OA coverage.
NULL definitions/comments may mean missing metadata permission. Record visibility with 00_discover.sql.
*/

-- Result 1: tables.csv
SELECT
    DB_NAME() AS database_name,
    s.name AS schema_name,
    t.name AS table_name,
    t.object_id,
    t.create_date,
    t.modify_date,
    CONVERT(nvarchar(max), ep.value) AS ms_description
FROM sys.tables AS t
JOIN sys.schemas AS s ON s.schema_id = t.schema_id
LEFT JOIN sys.extended_properties AS ep
    ON ep.class = 1 AND ep.major_id = t.object_id AND ep.minor_id = 0 AND ep.name = N'MS_Description'
WHERE t.is_ms_shipped = 0
ORDER BY s.name, t.name;

-- Result 2: views.csv. Useful for local virtual forms; no view/business data is read.
SELECT
    DB_NAME() AS database_name,
    s.name AS schema_name,
    v.name AS view_name,
    v.object_id,
    v.create_date,
    v.modify_date,
    CONVERT(nvarchar(max), ep.value) AS ms_description
FROM sys.views AS v
JOIN sys.schemas AS s ON s.schema_id = v.schema_id
LEFT JOIN sys.extended_properties AS ep
    ON ep.class = 1 AND ep.major_id = v.object_id AND ep.minor_id = 0 AND ep.name = N'MS_Description'
WHERE v.is_ms_shipped = 0
ORDER BY s.name, v.name;

-- Result 3: columns.csv. max_length is BYTES, not a general character-count limit.
;WITH PrimaryKeyColumns AS
(
    SELECT kc.parent_object_id AS object_id, ic.column_id, kc.name AS primary_key_name, ic.key_ordinal
    FROM sys.key_constraints AS kc
    JOIN sys.index_columns AS ic
        ON ic.object_id = kc.parent_object_id AND ic.index_id = kc.unique_index_id
    WHERE kc.type = N'PK' AND ic.key_ordinal > 0
)
SELECT
    DB_NAME() AS database_name,
    s.name AS schema_name,
    o.name AS table_name,
    o.type_desc AS object_type,
    o.object_id,
    c.column_id AS ordinal_position,
    c.name AS column_name,
    ts.name AS declared_type_schema,
    ty.name AS declared_type_name,
    TYPE_NAME(c.system_type_id) AS system_type_name,
    CASE WHEN ty.is_user_defined = 1 OR ty.is_assembly_type = 1
         THEN QUOTENAME(ts.name) + N'.' + QUOTENAME(ty.name)
         ELSE QUOTENAME(ty.name) +
              CASE WHEN ty.name IN (N'nvarchar', N'nchar')
                   THEN N'(' + CASE WHEN c.max_length = -1 THEN N'max'
                                    ELSE CONVERT(nvarchar(10), c.max_length / 2) END + N')'
                   WHEN ty.name IN (N'varchar', N'char', N'varbinary', N'binary')
                   THEN N'(' + CASE WHEN c.max_length = -1 THEN N'max'
                                    ELSE CONVERT(nvarchar(10), c.max_length) END + N')'
                   WHEN ty.name IN (N'decimal', N'numeric')
                   THEN N'(' + CONVERT(nvarchar(10), c.precision) + N',' + CONVERT(nvarchar(10), c.scale) + N')'
                   WHEN ty.name IN (N'datetime2', N'datetimeoffset', N'time')
                   THEN N'(' + CONVERT(nvarchar(10), c.scale) + N')'
                   WHEN ty.name = N'float'
                   THEN N'(' + CONVERT(nvarchar(10), c.precision) + N')'
                   ELSE N'' END
    END AS declared_type_sql,
    c.max_length AS max_length_bytes,
    CASE WHEN TYPE_NAME(c.system_type_id) IN (N'nvarchar', N'nchar')
         THEN CASE WHEN c.max_length = -1 THEN -1 ELSE c.max_length / 2 END
         ELSE NULL END AS unicode_declared_code_units,
    c.precision,
    c.scale,
    c.collation_name,
    c.is_nullable,
    c.is_identity,
    CONVERT(nvarchar(128), ident.seed_value) AS identity_seed,
    CONVERT(nvarchar(128), ident.increment_value) AS identity_increment,
    c.is_computed,
    comp.definition AS computed_definition,
    comp.is_persisted AS computed_is_persisted,
    COALESCE(dc.name, OBJECT_NAME(c.default_object_id)) AS default_name,
    COALESCE(dc.definition, OBJECT_DEFINITION(c.default_object_id)) AS default_definition,
    c.rule_object_id AS bound_rule_object_id,
    OBJECT_DEFINITION(c.rule_object_id) AS bound_rule_definition,
    pk.primary_key_name,
    pk.key_ordinal AS primary_key_ordinal,
    CONVERT(nvarchar(max), ep.value) AS ms_description
FROM sys.objects AS o
JOIN sys.schemas AS s ON s.schema_id = o.schema_id
JOIN sys.columns AS c ON c.object_id = o.object_id
JOIN sys.types AS ty ON ty.user_type_id = c.user_type_id
JOIN sys.schemas AS ts ON ts.schema_id = ty.schema_id
LEFT JOIN sys.default_constraints AS dc
    ON dc.object_id = c.default_object_id AND dc.parent_object_id = c.object_id AND dc.parent_column_id = c.column_id
LEFT JOIN sys.identity_columns AS ident ON ident.object_id = c.object_id AND ident.column_id = c.column_id
LEFT JOIN sys.computed_columns AS comp ON comp.object_id = c.object_id AND comp.column_id = c.column_id
LEFT JOIN PrimaryKeyColumns AS pk ON pk.object_id = c.object_id AND pk.column_id = c.column_id
LEFT JOIN sys.extended_properties AS ep
    ON ep.class = 1 AND ep.major_id = c.object_id AND ep.minor_id = c.column_id AND ep.name = N'MS_Description'
WHERE o.is_ms_shipped = 0 AND o.type IN (N'U', N'V')
ORDER BY s.name, o.name, c.column_id;

-- Result 4: keys.csv. One row per PK/UQ constraint column; preserves composite order.
SELECT
    DB_NAME() AS database_name,
    s.name AS schema_name,
    t.name AS table_name,
    kc.name AS constraint_name,
    kc.type_desc AS constraint_type,
    kc.unique_index_id,
    ic.key_ordinal,
    c.name AS column_name,
    ic.is_descending_key
FROM sys.key_constraints AS kc
JOIN sys.tables AS t ON t.object_id = kc.parent_object_id
JOIN sys.schemas AS s ON s.schema_id = t.schema_id
JOIN sys.index_columns AS ic ON ic.object_id = kc.parent_object_id AND ic.index_id = kc.unique_index_id
JOIN sys.columns AS c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
WHERE t.is_ms_shipped = 0 AND ic.key_ordinal > 0
ORDER BY s.name, t.name, kc.name, ic.key_ordinal;

-- Result 5: indexes.csv. One row per explicit index column; INCLUDE is separate from a key.
SELECT
    DB_NAME() AS database_name,
    s.name AS schema_name,
    o.name AS table_name,
    i.index_id,
    i.name AS index_name,
    i.type_desc AS index_type,
    i.is_unique,
    i.is_primary_key,
    i.is_unique_constraint,
    i.is_disabled,
    i.is_hypothetical,
    i.has_filter,
    i.filter_definition,
    ic.index_column_id,
    ic.key_ordinal,
    ic.partition_ordinal,
    ic.is_included_column,
    ic.is_descending_key,
    c.name AS column_name
FROM sys.indexes AS i
JOIN sys.objects AS o ON o.object_id = i.object_id
JOIN sys.schemas AS s ON s.schema_id = o.schema_id
LEFT JOIN sys.index_columns AS ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id
LEFT JOIN sys.columns AS c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
WHERE o.is_ms_shipped = 0 AND o.type IN (N'U', N'V') AND i.index_id > 0
ORDER BY s.name, o.name, i.index_id, ic.index_column_id;

-- Result 6: foreign_keys.csv. Physical FKs only; OA browser/logical links are a separate layer.
SELECT
    DB_NAME() AS database_name,
    ps.name AS schema_name,
    pt.name AS table_name,
    fk.name AS foreign_key_name,
    fkc.constraint_column_id AS key_ordinal,
    pc.name AS column_name,
    fkc.referenced_object_id,
    rs.name AS referenced_schema,
    rt.name AS referenced_table,
    rc.name AS referenced_column,
    fk.is_disabled,
    fk.is_not_trusted,
    fk.delete_referential_action_desc,
    fk.update_referential_action_desc
FROM sys.foreign_keys AS fk
JOIN sys.foreign_key_columns AS fkc ON fkc.constraint_object_id = fk.object_id
JOIN sys.tables AS pt ON pt.object_id = fkc.parent_object_id
JOIN sys.schemas AS ps ON ps.schema_id = pt.schema_id
JOIN sys.columns AS pc ON pc.object_id = fkc.parent_object_id AND pc.column_id = fkc.parent_column_id
LEFT JOIN sys.tables AS rt ON rt.object_id = fkc.referenced_object_id
LEFT JOIN sys.schemas AS rs ON rs.schema_id = rt.schema_id
LEFT JOIN sys.columns AS rc ON rc.object_id = fkc.referenced_object_id AND rc.column_id = fkc.referenced_column_id
WHERE pt.is_ms_shipped = 0
ORDER BY ps.name, pt.name, fk.name, fkc.constraint_column_id;

-- Result 7: extended_properties.csv. Preserve all table/column/index property names, not just MS_Description.
SELECT
    DB_NAME() AS database_name,
    s.name AS schema_name,
    o.name AS table_name,
    ep.class_desc AS property_class,
    ep.major_id,
    ep.minor_id,
    c.name AS column_name,
    i.name AS index_name,
    ep.name AS property_name,
    CONVERT(nvarchar(max), ep.value) AS property_value
FROM sys.extended_properties AS ep
JOIN sys.objects AS o ON o.object_id = ep.major_id
JOIN sys.schemas AS s ON s.schema_id = o.schema_id
LEFT JOIN sys.columns AS c ON ep.class = 1 AND c.object_id = ep.major_id AND c.column_id = ep.minor_id
LEFT JOIN sys.indexes AS i ON ep.class = 7 AND i.object_id = ep.major_id AND i.index_id = ep.minor_id
WHERE ep.class IN (1, 7) AND o.is_ms_shipped = 0 AND o.type IN (N'U', N'V')
ORDER BY s.name, o.name, ep.class, ep.minor_id, ep.name;

-- Result 8: check_constraints.csv. This is DDL metadata; no row validation is performed.
SELECT
    DB_NAME() AS database_name,
    s.name AS schema_name,
    t.name AS table_name,
    cc.name AS check_name,
    c.name AS column_name,
    cc.parent_column_id,
    cc.definition,
    cc.is_disabled,
    cc.is_not_trusted
FROM sys.check_constraints AS cc
JOIN sys.tables AS t ON t.object_id = cc.parent_object_id
JOIN sys.schemas AS s ON s.schema_id = t.schema_id
LEFT JOIN sys.columns AS c ON c.object_id = cc.parent_object_id AND c.column_id = cc.parent_column_id
WHERE t.is_ms_shipped = 0
ORDER BY s.name, t.name, cc.name;
