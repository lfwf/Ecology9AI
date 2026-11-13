# B08 scopes are derived only from registered source rows and explicit metadata.
function Get-InterfaceScopes {
    param($Method,[string]$SourceName,[System.Collections.IDictionary]$Tables,[hashtable]$Initial)
    $source=$Method.sources.$SourceName;$result=@{}
    if($source.PSObject.Properties.Name -notcontains 'scope_types'){return $result}
    foreach($scope in $source.scope_types.PSObject.Properties){
        $key=$scope.Name
        if($Initial.ContainsKey($key)){$values=@($Initial[$key])}
        else{
            if($Method.scope_mappings.PSObject.Properties.Name -notcontains $key){throw 'Unknown interface scope'}
            $mapping=$Method.scope_mappings.$key
            if(-not $Tables.Contains([string]$mapping.source)){throw 'Interface scope source missing'}
            $list=[Collections.Generic.List[object]]::new()
            foreach($row in $Tables[$mapping.source]){
                $matches=$true
                if($mapping.PSObject.Properties.Name -contains 'filter'){
                    foreach($filter in $mapping.filter.PSObject.Properties){if([string]$row.($filter.Name) -cne [string]$filter.Value){$matches=$false;break}}
                }
                if(-not $matches){continue}
                $value=$row.($mapping.column)
                if($null -eq $value -or [string]::IsNullOrWhiteSpace([string]$value)){continue}
                if($scope.Value -ceq 'int'){
                    $number=0
                    if(-not [int]::TryParse([string]$value,[ref]$number)){
                        $script:scopeWarnings.Add([pscustomobject]@{kind='interface_reference_syntax_unparsed';source=$mapping.source;id=$row.id;column=$mapping.column})
                        continue
                    }
                    if($number -gt 0){$list.Add([int]$number)}
                }elseif($scope.Value -ceq 'string'){$list.Add([string]$value)}
                else{throw 'Unknown interface scope type'}
            }
            $values=@($list.ToArray()|Sort-Object -CaseSensitive -Unique)
        }
        $partitioned=$source.PSObject.Properties.Name -contains 'partition_scope' -and $source.partition_scope -ceq $key
        $cap=if($partitioned){$Method.limits.max_expands}else{$Method.limits.max_scope_ids}
        if($values.Count -gt $cap){throw 'Interface scope cap exceeded'}
        $result[$key]=$values
    }
    return $result
}
