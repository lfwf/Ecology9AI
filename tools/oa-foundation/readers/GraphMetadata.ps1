# Only sys catalog queries. Requested object names are values, never executable identifiers.
function Read-GraphPhysicalMetadata {
    param($Session,$Method,[string[]]$Names)
    $namesSorted=@($Names|Sort-Object -CaseSensitive -Unique)
    if($namesSorted.Count -gt $Method.limits.max_physical_tables -or $namesSorted.Count -gt 1500){throw 'Physical reference scope exceeded'}
    if(-not $namesSorted.Count){return [pscustomobject]@{physical_columns=@();physical_keys=@();physical_foreign_keys=@()}}
    $parameters=@{};$placeholders=@();$i=0
    foreach($table in $namesSorted){
        if([string]::IsNullOrEmpty($table) -or $table.Length -gt 128){throw 'Invalid physical object reference'}
        $name='@p'+$i;$parameters[$name]=[string]$table;$placeholders+=$name;$i++
    }
    $filter=$placeholders -join ','
    $columnSql=@'
SELECT s.name AS schema_name,o.name AS table_name,c.column_id,c.name AS column_name,t.name AS data_type,
c.max_length,c.precision,c.scale,c.is_nullable,c.is_identity,c.is_computed
FROM sys.objects o JOIN sys.schemas s ON s.schema_id=o.schema_id JOIN sys.columns c ON c.object_id=o.object_id
JOIN sys.types t ON t.user_type_id=c.user_type_id WHERE o.type IN ('U','V') AND o.name IN (
'@
    $columns=Read-OaPages $Session ($columnSql+$filter+')') 's.name,o.name,c.column_id' $Method.limits.max_physical_columns $parameters
    $keySql=@'
SELECT s.name AS schema_name,o.name AS table_name,i.name AS index_name,i.is_primary_key,i.is_unique,
i.has_filter,i.is_disabled,i.is_hypothetical,ic.key_ordinal,c.name AS column_name
FROM sys.objects o JOIN sys.schemas s ON s.schema_id=o.schema_id
JOIN sys.indexes i ON i.object_id=o.object_id JOIN sys.index_columns ic ON ic.object_id=i.object_id AND ic.index_id=i.index_id
JOIN sys.columns c ON c.object_id=ic.object_id AND c.column_id=ic.column_id
WHERE ic.key_ordinal>0 AND o.name IN (
'@
    $keys=Read-OaPages $Session ($keySql+$filter+')') 's.name,o.name,i.name,ic.key_ordinal' $Method.limits.max_physical_columns $parameters
    $fkSql=@'
SELECT fk.name AS constraint_name,s.name AS child_schema,ps.name AS parent_schema,
child.name AS child_table,cc.name AS child_column,parent.name AS parent_table,pc.name AS parent_column,
fkc.constraint_column_id,fk.is_disabled,fk.is_not_trusted
FROM sys.foreign_keys fk JOIN sys.foreign_key_columns fkc ON fk.object_id=fkc.constraint_object_id
JOIN sys.objects child ON child.object_id=fk.parent_object_id JOIN sys.schemas s ON s.schema_id=child.schema_id
JOIN sys.objects parent ON parent.object_id=fk.referenced_object_id JOIN sys.schemas ps ON ps.schema_id=parent.schema_id
JOIN sys.columns cc ON cc.object_id=child.object_id AND cc.column_id=fkc.parent_column_id
JOIN sys.columns pc ON pc.object_id=parent.object_id AND pc.column_id=fkc.referenced_column_id WHERE child.name IN (
'@
    $foreign=Read-OaPages $Session ($fkSql+$filter+')') 's.name,child.name,fk.name,fkc.constraint_column_id' $Method.limits.max_physical_columns $parameters
    return [pscustomobject]@{physical_columns=$columns.rows;physical_keys=$keys.rows;physical_foreign_keys=$foreign.rows}
}
