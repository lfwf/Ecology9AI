# Native configuration schema contract reused from B02 reader.
function Get-ConfigSchema {
    $parameters=@{};$names=[Collections.Generic.List[string]]::new();$i=0
    foreach($source in $method.sources.PSObject.Properties){
        $name='@source'+$i;$parameters[$name]=$source.Name;$names.Add($name);$i++
    }
    $sql=@'
SELECT o.name AS object_name,c.name AS column_name,t.name AS data_type,c.max_length,c.precision,c.scale,c.is_nullable,
HAS_PERMS_BY_NAME(QUOTENAME(s.name)+'.'+QUOTENAME(o.name),'OBJECT','SELECT') AS can_select
FROM sys.objects o JOIN sys.schemas s ON s.schema_id=o.schema_id
JOIN sys.columns c ON c.object_id=o.object_id JOIN sys.types t ON t.user_type_id=c.user_type_id
WHERE s.name='dbo' AND o.type='U' AND o.name IN (
'@
    $sql += ($names -join ',')+') ORDER BY o.name,c.column_id;'
    $all=Invoke-OaQuery $session $sql $parameters 1500
    $selected=[Collections.Generic.List[object]]::new()
    foreach($source in $method.sources.PSObject.Properties){
        foreach($field in $source.Value.columns.PSObject.Properties){
            $matches=@($all | Where-Object {$_.object_name -ieq $source.Name -and $_.column_name -ceq $field.Value.source_name})
            if($matches.Count -ne 1 -or $matches[0].data_type -cne $field.Value.data_type -or $matches[0].can_select -ne 1){throw 'Registered schema unavailable or changed'}
            $selected.Add($matches[0])
        }
    }
    return ,$selected.ToArray()
}
