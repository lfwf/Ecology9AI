[CmdletBinding()]
param([Parameter(Mandatory=$true)][ValidateSet('B03','B04','B05','B06','B07','B08','B09')][string]$Category,
      [Parameter(Mandatory=$true)][string]$ConnectionDirectory,
      [Parameter(Mandatory=$true)][string]$DependencyPath,
      [Parameter(Mandatory=$true)][string]$OutputPath)
. (Join-Path $PSScriptRoot 'SqlSession.ps1')
$ErrorActionPreference='Stop'
$session=$null;$first=$null;$second=$null;$currentSource=$null;$failureCode='reader_error';$stage='initialization';$started=[DateTimeOffset]::UtcNow.ToString('o')
$homeDirectory=Split-Path $PSScriptRoot -Parent
$method=Get-Content -LiteralPath (Join-Path $homeDirectory ('registry/'+$Category+'.json')) -Encoding UTF8 -Raw | ConvertFrom-Json
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
function Read-ConfigurationPass {
    param([switch]$HashesOnly)
    $tables=[ordered]@{};$checks=[ordered]@{}
    $retain=[Collections.Generic.HashSet[string]]::new()
    foreach($definition in $method.sources.PSObject.Properties){
        if($definition.Value.PSObject.Properties.Name -contains 'reference_scope'){
            foreach($r in $definition.Value.reference_scope.references){[void]$retain.Add([string]$r.source)}
        }
        if($definition.Value.PSObject.Properties.Name -contains 'partition_by'){[void]$retain.Add([string]$definition.Value.partition_by.source)}
    }
    foreach($source in $method.sources.PSObject.Properties){
        $script:currentSource=$source.Name
        if($source.Value.PSObject.Properties.Name -contains 'reference_scope'){
            $result=Read-OaReferencedScope $session $source.Value $tables
        } elseif($source.Value.PSObject.Properties.Name -contains 'partition_by'){
            $result=Read-OaPartitions $session $source.Value $tables
        } else {$result=Read-OaPages $session $source.Value.sql $source.Value.order_by $source.Value.row_cap}
        $checks[$source.Name]=[ordered]@{complete=$true;row_count=$result.rows.Count;pages=$result.pages;hash_capture=(Get-OaHash $result.rows)}
        if(-not $HashesOnly -or $retain.Contains([string]$source.Name)){$tables[$source.Name]=$result.rows}
        $result=$null
    }
    if($method.metadata_sources.Count){throw 'Category requires a metadata adapter'}
    return [pscustomobject]@{tables=$tables;checks=$checks}
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
    $stage='second_pass';$second=Read-ConfigurationPass -HashesOnly
    $stage='consistency'
    if((Get-OaHash $schema) -cne (Get-OaHash (Get-ConfigSchema))){$failureCode='schema_changed';throw 'Schema changed during capture'}
    if((Get-OaHash (Get-WorkflowAnchor)) -cne (Get-OaHash $seed.tables.workflow_base)){$failureCode='dependency_changed';throw 'Workflow directory changed during capture'}
    foreach($source in $first.tables.Keys){
        $hash1=$first.checks[$source]['hash_capture'];$hash2=$second.checks[$source]['hash_capture']
        if($hash1 -cne $hash2){$currentSource=$source;$failureCode='source_content_changed';throw 'Configuration or metadata changed during capture'}
        $first.checks[$source]['hash_first']=$hash1;$first.checks[$source]['hash_second']=$hash2
    }
    $stage='save'
    $result=[ordered]@{format_version=1;category=$Category;method_version=$method.method_version;
        started_at=$started;ended_at=[DateTimeOffset]::UtcNow.ToString('o');source_identity=$sourceIdentity;
        transport=[ordered]@{encrypt=$true;trust_server_certificate=$session.Profile.trust_server_certificate};
        business_rows_read=0;scope=$method.scope;dependency_sha256=(Get-FileHash -LiteralPath $DependencyPath -Algorithm SHA256).Hash;
        consistency='two equal sequential reads; READ COMMITTED, not a transaction snapshot';
        permission_audit='selected source SELECT and explicit broad roles only; no write test';
        implementation_hashes=[ordered]@{reader=(Get-FileHash -LiteralPath $PSCommandPath).Hash;session=(Get-FileHash -LiteralPath (Join-Path $PSScriptRoot 'SqlSession.ps1')).Hash;registry=(Get-FileHash -LiteralPath (Join-Path $homeDirectory ('registry/'+$Category+'.json'))).Hash};
        schema=$schema;tables=$first.tables;checks=$first.checks}
    Write-OaCapture $OutputPath $result
    Write-Output (ConvertTo-Json -InputObject ([ordered]@{status='captured';category=$Category;business_rows_read=0}) -Compress)
} catch {
    $failure=[ordered]@{status='failed';stage=$stage;failure_code=$failureCode;source=$currentSource;business_rows_read=0}
    $diagnostic=Join-Path (Split-Path $OutputPath -Parent) 'checks.json'
    try{if(-not(Test-Path -LiteralPath $diagnostic)){Write-OaCapture $diagnostic ([ordered]@{failure=$failure;first_checks=if($null -ne $first){$first.checks}else{$null};second_checks=if($null -ne $second){$second.checks}else{$null}})}}catch{}
    Write-Output (ConvertTo-Json -InputObject $failure -Depth 6 -Compress)
    exit 1
} finally {Close-OaSession $session}
