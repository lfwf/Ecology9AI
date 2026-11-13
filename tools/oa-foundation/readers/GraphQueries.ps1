# Registered reference-graph helpers. SQL bodies come only from the checked registry.
function Read-GraphSource {
    param($Session,$Method,[string]$SourceName,[hashtable]$Scopes=@{},[switch]$Unpartitioned)
    $script:currentSource=$SourceName
    if($Method.sources.PSObject.Properties.Name -notcontains $SourceName){throw 'Unknown graph source'}
    $source=$Method.sources.$SourceName
    if(-not $Unpartitioned -and $source.PSObject.Properties.Name -contains 'partition_scope'){
        $key=[string]$source.partition_scope;$size=[int]$source.partition_size
        if($size -lt 1 -or $size -gt 1000 -or -not $Scopes.ContainsKey($key)){throw 'Invalid scope partition'}
        $values=@($Scopes[$key]|Sort-Object -CaseSensitive -Unique)
        $rows=[Collections.Generic.List[object]]::new();$pages=[Collections.Generic.List[object]]::new()
        for($offset=0;$offset -lt $values.Count;$offset+=$size){
            $sub=@{};foreach($scopeKey in $Scopes.Keys){$sub[$scopeKey]=$Scopes[$scopeKey]}
            $last=[Math]::Min($offset+$size,$values.Count)-1;$sub[$key]=@($values[$offset..$last])
            $block=Read-GraphSource $Session $Method $SourceName $sub -Unpartitioned
            foreach($row in $block.rows){if($rows.Count -ge $source.row_cap){throw 'Graph source total row cap exceeded'};$rows.Add($row)}
            foreach($page in $block.pages){$pages.Add($page)}
        }
        return [pscustomobject]@{rows=$rows.ToArray();pages=$pages.ToArray();complete=$true;scope_counts=[ordered]@{$key=$values.Count}}
    }
    $sql=[string]$source.sql;$parameters=@{};$anyValues=$false
    $scopeCounts=[ordered]@{}
    if($source.PSObject.Properties.Name -contains 'scope_types'){
        foreach($scope in $source.scope_types.PSObject.Properties){
            if(-not $Scopes.ContainsKey($scope.Name)){throw 'Missing typed graph scope'}
            $values=@($Scopes[$scope.Name] | Sort-Object -CaseSensitive -Unique)
            $scopeCounts[$scope.Name]=$values.Count
            $placeholders=[Collections.Generic.List[string]]::new();$j=0
            foreach($value in $values){
                if($parameters.Count -ge 1800){throw 'Graph parameter limit exceeded'}
                $name='@g_'+$scope.Name+'_'+$j;$j++
                if($scope.Value -ceq 'int'){
                    $integer=0
                    if(-not [int]::TryParse([string]$value,[ref]$integer)){throw 'Invalid integer graph reference'}
                    $parameters[$name]=[int]$integer
                } elseif($scope.Value -ceq 'string'){
                    if([string]::IsNullOrEmpty([string]$value) -or ([string]$value).Length -gt 128){throw 'Invalid string graph reference'}
                    $parameters[$name]=[string]$value
                }else{throw 'Unknown scope parameter type'}
                $placeholders.Add($name);$anyValues=$true
            }
            $replacement=if($placeholders.Count){$placeholders -join ','}else{'NULL'}
            $sql=$sql.Replace('{'+$scope.Name+'}',$replacement)
        }
        $mustExecute=$source.PSObject.Properties.Name -contains 'execute_with_empty_scopes' -and $source.execute_with_empty_scopes -eq $true
        if(-not $anyValues -and -not $mustExecute){return [pscustomobject]@{rows=@();pages=@();complete=$true;scope_counts=$scopeCounts}}
    }
    if($sql -match '\{[A-Za-z_]+\}'){throw 'Unbound graph placeholder'}
    $result=Read-OaPages $Session $sql $source.order_by $source.row_cap $parameters
    $result | Add-Member -NotePropertyName scope_counts -NotePropertyValue $scopeCounts
    return $result
}
function Get-GraphSchema {
    param($Session,$Method)
    $parameters=@{};$names=[Collections.Generic.List[string]]::new();$i=0
    foreach($source in $Method.sources.PSObject.Properties){
        $objectName=if($source.Value.PSObject.Properties.Name -contains 'object_name'){$source.Value.object_name}else{$source.Name}
        $name='@s'+$i;$parameters[$name]=[string]$objectName;$names.Add($name);$i++
    }
    $sql=@'
SELECT o.name AS object_name,c.name AS column_name,t.name AS data_type,c.max_length,c.precision,c.scale,c.is_nullable,
HAS_PERMS_BY_NAME(QUOTENAME(s.name)+'.'+QUOTENAME(o.name),'OBJECT','SELECT') AS can_select
FROM sys.objects o JOIN sys.schemas s ON s.schema_id=o.schema_id JOIN sys.columns c ON c.object_id=o.object_id
JOIN sys.types t ON t.user_type_id=c.user_type_id WHERE s.name='dbo' AND o.type='U' AND o.name IN (
'@
    $all=Invoke-OaQuery $Session ($sql+($names -join ',')+') ORDER BY o.name,c.column_id;') $parameters 2500
    $selected=[Collections.Generic.List[object]]::new()
    foreach($source in $Method.sources.PSObject.Properties){
        $objectName=if($source.Value.PSObject.Properties.Name -contains 'object_name'){$source.Value.object_name}else{$source.Name}
        foreach($field in $source.Value.columns.PSObject.Properties){
            $matches=@($all|Where-Object {$_.object_name -ieq $objectName -and $_.column_name -ceq $field.Value.source_name})
            if($matches.Count -ne 1 -or $matches[0].data_type -cne $field.Value.data_type -or $matches[0].can_select -ne 1){$script:currentSource=$source.Name;throw 'Registered graph schema unavailable'}
            $selected.Add([pscustomobject]@{source_key=$source.Name;object_name=$matches[0].object_name;column_name=$matches[0].column_name;data_type=$matches[0].data_type;max_length=$matches[0].max_length;precision=$matches[0].precision;scale=$matches[0].scale;is_nullable=$matches[0].is_nullable})
        }
    }
    return ,$selected.ToArray()
}
function Add-GraphIntegers {
    param($Set,$Rows,[string]$Column,[switch]$PositiveOnly)
    foreach($row in $Rows){
        $value=$row.$Column
        if($null -eq $value){continue}
        $integer=0
        if(-not [int]::TryParse([string]$value,[ref]$integer)){throw 'Invalid configured integer reference'}
        if(-not $PositiveOnly -or $integer -gt 0){[void]$Set.Add($integer)}
    }
}
function Add-GraphCodes {
    param($Set,$Rows)
    foreach($row in $Rows){
        if($null -ne $row.fielddbtype -and ([string]$row.fielddbtype).StartsWith('browser.')){
            $code=([string]$row.fielddbtype).Substring(8)
            if($code.Length){[void]$Set.Add($code)}
        }
    }
}
