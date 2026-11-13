[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$ConnectionDirectory,
      [Parameter(Mandatory=$true)][string]$DependencyPath,
      [Parameter(Mandatory=$true)][string]$OutputPath)
. (Join-Path $PSScriptRoot 'SqlSession.ps1')
. (Join-Path $PSScriptRoot 'MetadataQueries.ps1')
$ErrorActionPreference='Stop';$homeDirectory=Split-Path $PSScriptRoot -Parent
$method=Get-Content (Join-Path $homeDirectory 'registry/B09.json') -Raw -Encoding UTF8|ConvertFrom-Json
$seed=Get-Content -LiteralPath $DependencyPath -Raw -Encoding UTF8|ConvertFrom-Json
$session=$null;$first=$null;$second=$null;$stage='initialization';$currentSource=$null
$started=[DateTimeOffset]::UtcNow.ToString('o')
function Read-RuntimeMetadataPass {
    $tables=[ordered]@{};$contracts=[ordered]@{};$checks=[ordered]@{}
    $parameters=@{};$names=[Collections.Generic.List[string]]::new();$i=0
    foreach($target in $method.targets){
        if([string]::IsNullOrWhiteSpace($target.name) -or $target.name.Length -gt 128){throw 'Invalid metadata target'}
        $key='@m'+$i;$i++;$parameters[$key]=[string]$target.name;$names.Add($key)
    }
    if($names.Count -gt $method.limits.max_targets -or $names.Count -eq 0){throw 'Metadata target cap exceeded'}
    foreach($entry in $method.metadata_queries.PSObject.Properties){
        $script:currentSource=$entry.Name
        $sql=([string]$entry.Value.sql).Replace('{object_names}',($names -join ','))
        if($sql -match '\{[A-Za-z_]+\}'){throw 'Unbound metadata placeholder'}
        $result=Read-MetadataSource $session $sql $parameters $entry.Value.row_cap
        $tables[$entry.Name]=$result.rows;$contracts[$entry.Name]=$result.contract
        $checks[$entry.Name]=[ordered]@{complete=$true;row_count=$result.rows.Count;pages=@();hash_capture=(Get-OaHash $result.rows);contract_hash=(Get-OaHash $result.contract)}
    }
    return [pscustomobject]@{tables=$tables;schema=$contracts;checks=$checks}
}
try{
    if(Test-Path -LiteralPath $OutputPath){throw 'Output exists'}
    if($seed.category -cne 'B01' -or $seed.business_rows_read -ne 0){throw 'Invalid metadata dependency'}
    $stage='connection';$session=Open-OaSession $ConnectionDirectory $method.limits.read_budget_seconds
    $identity=[ordered]@{server=$session.Profile.server;port=$session.Profile.port;database=$session.Identity.database_name;server_identity=$session.Identity.server_identity;server_version=$session.Identity.server_version;login=$session.Identity.original_login;database_user=$session.Identity.database_user}
    if((Get-OaHash $identity) -cne (Get-OaHash $seed.source_identity)){throw 'Metadata source identity mismatch'}
    $stage='first_pass';$first=Read-RuntimeMetadataPass
    $stage='second_pass';$second=Read-RuntimeMetadataPass
    $stage='consistency'
    if((Get-OaHash $first.schema) -cne (Get-OaHash $second.schema)){throw 'Metadata result contract changed'}
    foreach($entry in $first.tables.GetEnumerator()){
        $name=$entry.Key;$currentSource=$name;$h1=$first.checks[$name].hash_capture;$h2=$second.checks[$name].hash_capture
        if($h1 -cne $h2){throw 'Runtime object metadata changed'}
        $first.checks[$name]['hash_first']=$h1;$first.checks[$name]['hash_second']=$h2
    }
    $stage='save'
    $hashes=[ordered]@{reader=(Get-FileHash $PSCommandPath).Hash;session=(Get-FileHash (Join-Path $PSScriptRoot 'SqlSession.ps1')).Hash;registry=(Get-FileHash (Join-Path $homeDirectory 'registry/B09.json')).Hash;metadata=(Get-FileHash (Join-Path $PSScriptRoot 'MetadataQueries.ps1')).Hash}
    Write-OaCapture $OutputPath ([ordered]@{format_version=1;category='B09';method_version=$method.method_version;scope=$method.scope;started_at=$started;ended_at=[DateTimeOffset]::UtcNow.ToString('o');source_identity=$identity;business_rows_read=0;transport=[ordered]@{encrypt=$true;trust_server_certificate=$session.Profile.trust_server_certificate};dependency_sha256=(Get-FileHash $DependencyPath).Hash;schema=$first.schema;tables=$first.tables;checks=$first.checks;implementation_hashes=$hashes;consistency='two equal sequential sys metadata reads; not a transaction snapshot';permission_audit='selected metadata visibility and broad-role checks only; no write test'})
    '{"status":"captured","category":"B09","business_rows_read":0}'
}catch{
    $failure=[ordered]@{status='failed';stage=$stage;source=$currentSource;failure_code='reader_error';business_rows_read=0}
    $ex=$_.Exception;while($null -ne $ex){if($ex.PSObject.Properties.Name -contains 'Number'){$failure['sql_error_number']=$ex.Number};$ex=$ex.InnerException}
    try{Write-OaCapture (Join-Path (Split-Path $OutputPath -Parent) 'checks.json') ([ordered]@{failure=$failure;first_checks=if($null -ne $first){$first.checks}else{$null};second_checks=if($null -ne $second){$second.checks}else{$null}})}catch{}
    $failure|ConvertTo-Json -Depth 5 -Compress;exit 1
}finally{Close-OaSession $session}
