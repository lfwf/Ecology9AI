# Physical metadata helper reused from registered B02 reader.
function Read-PhysicalMetadata {
    param($Tables)
    $names=[Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach($form in $Tables['workflow_bill']){if($form.tablename){[void]$names.Add($form.tablename)};if($form.detailtablename){[void]$names.Add($form.detailtablename)}}
    foreach($detail in $Tables['Workflow_billdetailtable']){if($detail.tablename){[void]$names.Add($detail.tablename)}}
    foreach($field in $Tables['workflow_billfield']){if($field.detailtable){[void]$names.Add($field.detailtable)}}
    if($Tables['workflow_formbase'].Count){[void]$names.Add('workflow_form');[void]$names.Add('workflow_formdetail')}
    if($names.Count -gt $method.limits.max_physical_tables -or $names.Count -eq 0){throw 'Physical metadata scope exceeded or empty'}
    $parameters=@{};$placeholders=[Collections.Generic.List[string]]::new();$i=0
    foreach($table in ($names | Sort-Object)){
        if($table.Length -gt 128){throw 'Physical object identifier too long'}
        $name='@table'+$i;$parameters[$name]=$table;$placeholders.Add($name);$i++
    }
    $filter=$placeholders -join ','
    $columnSql=@'
SELECT o.name AS table_name,c.column_id,c.name AS column_name,t.name AS data_type,c.max_length,c.precision,c.scale,c.is_nullable,c.is_identity,c.is_computed
FROM sys.objects o JOIN sys.schemas s ON s.schema_id=o.schema_id
JOIN sys.columns c ON c.object_id=o.object_id JOIN sys.types t ON t.user_type_id=c.user_type_id
WHERE s.name='dbo' AND o.type IN ('U','V') AND o.name IN (
'@
    $columns=Invoke-OaQuery $session ($columnSql+$filter+') ORDER BY o.name,c.column_id;') $parameters $method.limits.max_physical_columns
    $keySql=@'
SELECT o.name AS table_name,i.name AS index_name,i.is_primary_key,i.is_unique,i.has_filter,i.is_disabled,i.is_hypothetical,ic.key_ordinal,c.name AS column_name
FROM sys.objects o JOIN sys.schemas s ON s.schema_id=o.schema_id
JOIN sys.indexes i ON i.object_id=o.object_id JOIN sys.index_columns ic ON ic.object_id=i.object_id AND ic.index_id=i.index_id
JOIN sys.columns c ON c.object_id=ic.object_id AND c.column_id=ic.column_id
WHERE s.name='dbo' AND ic.key_ordinal>0 AND o.name IN (
'@
    $keys=Invoke-OaQuery $session ($keySql+$filter+') ORDER BY o.name,i.name,ic.key_ordinal;') $parameters 10000
    $foreignSql=@'
SELECT fk.name AS constraint_name,s.name AS child_schema,ps.name AS parent_schema,child.name AS child_table,cc.name AS child_column,parent.name AS parent_table,pc.name AS parent_column,
fkc.constraint_column_id,fk.is_disabled,fk.is_not_trusted
FROM sys.foreign_keys fk JOIN sys.foreign_key_columns fkc ON fk.object_id=fkc.constraint_object_id
JOIN sys.objects child ON child.object_id=fk.parent_object_id JOIN sys.schemas s ON s.schema_id=child.schema_id
JOIN sys.objects parent ON parent.object_id=fk.referenced_object_id JOIN sys.schemas ps ON ps.schema_id=parent.schema_id
JOIN sys.columns cc ON cc.object_id=child.object_id AND cc.column_id=fkc.parent_column_id
JOIN sys.columns pc ON pc.object_id=parent.object_id AND pc.column_id=fkc.referenced_column_id
WHERE s.name='dbo' AND child.name IN (
'@
    $foreign=Invoke-OaQuery $session ($foreignSql+$filter+') ORDER BY child.name,fk.name,fkc.constraint_column_id;') $parameters 10000
    return [pscustomobject]@{physical_columns=$columns;physical_keys=$keys;physical_foreign_keys=$foreign;requested_tables=@($names | Sort-Object)}
}
