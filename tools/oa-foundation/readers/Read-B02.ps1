[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$ConnectionDirectory,
      [Parameter(Mandatory=$true)][string]$DependencyPath,
      [Parameter(Mandatory=$true)][string]$OutputPath)
. (Join-Path $PSScriptRoot 'SqlSession.ps1')
$ErrorActionPreference='Stop'
$session=$null;$stage='initialization';$started=[DateTimeOffset]::UtcNow.ToString('o')
$homeDirectory=Split-Path $PSScriptRoot -Parent
$method=Get-Content -LiteralPath (Join-Path $homeDirectory 'registry/B02.json') -Encoding UTF8 -Raw | ConvertFrom-Json
$seed=Get-Content -LiteralPath $DependencyPath -Encoding UTF8 -Raw | ConvertFrom-Json
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
function Get-WorkflowAnchor {
    $registry=Get-Content -LiteralPath (Join-Path $homeDirectory 'registry/B01.json') -Encoding UTF8 -Raw | ConvertFrom-Json
    $fields=($registry.tables.workflow_base.PSObject.Properties.Name | ForEach-Object {'['+$_+']'}) -join ','
    $result=Read-OaPages $session ('SELECT '+$fields+' FROM dbo.workflow_base') 'id' 20000
    return ,$result.rows
}
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
function Read-ConfigurationPass {
    $tables=[ordered]@{};$checks=[ordered]@{}
    foreach($source in $method.sources.PSObject.Properties){
        $result=Read-OaPages $session $source.Value.sql $source.Value.order_by $source.Value.row_cap
        $tables[$source.Name]=$result.rows
        $checks[$source.Name]=[ordered]@{complete=$true;row_count=$result.rows.Count;pages=$result.pages}
    }
    $physical=Read-PhysicalMetadata $tables
    foreach($name in $method.metadata_sources){
        $tables[$name]=$physical.$name
        $checks[$name]=[ordered]@{complete=$true;row_count=$physical.$name.Count;pages=@()}
    }
    return [pscustomobject]@{tables=$tables;checks=$checks;physical_scope=$physical.requested_tables}
}
try {
    if(Test-Path -LiteralPath $OutputPath){throw 'Output exists'}
    if($seed.category -cne 'B01' -or $seed.business_rows_read -ne 0 -or $seed.tables.workflow_base.Count -eq 0){throw 'Invalid dependency'}
    $stage='connection';$session=Open-OaSession $ConnectionDirectory $method.limits.read_budget_seconds
    $sourceIdentity=[ordered]@{server=$session.Profile.server;port=$session.Profile.port;database=$session.Identity.database_name;
        server_identity=$session.Identity.server_identity;server_version=$session.Identity.server_version;
        login=$session.Identity.original_login;database_user=$session.Identity.database_user}
    $stage='dependency'
    if((Get-OaHash $sourceIdentity) -cne (Get-OaHash $seed.source_identity)){throw 'Dependency belongs to another source'}
    if((Get-OaHash (Get-WorkflowAnchor)) -cne (Get-OaHash $seed.tables.workflow_base)){throw 'Workflow directory changed; refresh dependency'}
    $stage='schema';$schema=Get-ConfigSchema
    $stage='first_pass';$first=Read-ConfigurationPass
    $stage='second_pass';$second=Read-ConfigurationPass
    $stage='consistency'
    if((Get-OaHash $schema) -cne (Get-OaHash (Get-ConfigSchema))){throw 'Schema changed during capture'}
    if((Get-OaHash (Get-WorkflowAnchor)) -cne (Get-OaHash $seed.tables.workflow_base)){throw 'Workflow directory changed during capture'}
    foreach($source in $first.tables.Keys){
        $hash1=Get-OaHash $first.tables[$source];$hash2=Get-OaHash $second.tables[$source]
        if($hash1 -cne $hash2){throw 'Configuration or metadata changed during capture'}
        $first.checks[$source]['hash_first']=$hash1;$first.checks[$source]['hash_second']=$hash2
    }
    $stage='save'
    $result=[ordered]@{format_version=1;category='B02';method_version=$method.method_version;
        started_at=$started;ended_at=[DateTimeOffset]::UtcNow.ToString('o');source_identity=$sourceIdentity;
        transport=[ordered]@{encrypt=$true;trust_server_certificate=$session.Profile.trust_server_certificate};
        business_rows_read=0;scope=$method.scope;dependency_sha256=(Get-FileHash -LiteralPath $DependencyPath -Algorithm SHA256).Hash;
        consistency='two equal sequential reads; READ COMMITTED, not a transaction snapshot';
        permission_audit='selected source SELECT and explicit broad roles only; no write test';
        implementation_hashes=[ordered]@{reader=(Get-FileHash -LiteralPath $PSCommandPath).Hash;session=(Get-FileHash -LiteralPath (Join-Path $PSScriptRoot 'SqlSession.ps1')).Hash;registry=(Get-FileHash -LiteralPath (Join-Path $homeDirectory 'registry/B02.json')).Hash};
        schema=$schema;physical_scope=$first.physical_scope;tables=$first.tables;checks=$first.checks}
    Write-OaCapture $OutputPath $result
    Write-Output '{"status":"captured","category":"B02","business_rows_read":0}'
} catch {
    Write-Output ('{"status":"failed","stage":"'+$stage+'","business_rows_read":0}')
    exit 1
} finally {Close-OaSession $session}
