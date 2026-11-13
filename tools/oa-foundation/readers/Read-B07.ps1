[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$ConnectionDirectory,
      [Parameter(Mandatory=$true)][string]$DependencyPath,
      [Parameter(Mandatory=$true)][string]$RelationDependencyPath,
      [Parameter(Mandatory=$true)][string]$OutputPath)
. (Join-Path $PSScriptRoot 'SqlSession.ps1')
. (Join-Path $PSScriptRoot 'GraphQueries.ps1')
. (Join-Path $PSScriptRoot 'ReportScopes.ps1')
$ErrorActionPreference='Stop'
$homeDirectory=Split-Path $PSScriptRoot -Parent
$method=Get-Content (Join-Path $homeDirectory 'registry/B07.json') -Raw -Encoding UTF8|ConvertFrom-Json
$seed=Get-Content -LiteralPath $DependencyPath -Raw -Encoding UTF8|ConvertFrom-Json
$relations=Get-Content -LiteralPath $RelationDependencyPath -Raw -Encoding UTF8|ConvertFrom-Json
$session=$null;$first=$null;$second=$null;$stage='initialization';$currentSource=$null
$started=[DateTimeOffset]::UtcNow.ToString('o')
function Get-WorkflowAnchor {
    $r=Get-Content (Join-Path $homeDirectory 'registry/B01.json') -Raw -Encoding UTF8|ConvertFrom-Json
    $fields=($r.tables.workflow_base.PSObject.Properties.Name|ForEach-Object {'['+$_+']'}) -join ','
    return ,(Read-OaPages $session ('SELECT '+$fields+' FROM dbo.workflow_base') 'id' 20000).rows
}
function Read-ReportPass {
    $tables=[ordered]@{};$checks=[ordered]@{}
    $initial=@{
      mode_ids=@($relations.tables.modeinfo|ForEach-Object {[int]$_.id})
      form_ids=@($relations.tables.workflow_bill|ForEach-Object {[int]$_.id})
      label_ids=@($relations.tables.HtmlLabelInfo|ForEach-Object {[int]$_.indexid}|Sort-Object -Unique)
    }
    foreach($source in $method.sources.PSObject.Properties){
        $script:currentSource=$source.Name;$scopes=@{}
        if($source.Value.PSObject.Properties.Name -contains 'scope_types'){
            foreach($key in $source.Value.scope_types.PSObject.Properties.Name){
                if($key -eq 'selected_standard_ids'){$values=Select-OaReportScope $tables['Workflow_Report_scope'] $seed.tables.workflow_base 'reportwfid'}
                elseif($key -eq 'selected_custom_ids'){$values=Select-OaReportScope $tables['workflow_customreport_scope'] $seed.tables.workflow_base 'workflowid'}
                elseif($initial.ContainsKey($key)){$values=@($initial[$key])}
                elseif($method.scope_mappings.PSObject.Properties.Name -contains $key){
                    $map=$method.scope_mappings.$key
                    $inputs=if($map.PSObject.Properties.Name -contains 'sources'){@($map.sources)}else{@($map.source)}
                    $collected=[Collections.Generic.HashSet[int]]::new()
                    foreach($inputSource in $inputs){
                        if(-not $tables.Contains([string]$inputSource)){throw 'Report scope dependency unavailable'}
                        foreach($row in $tables[$inputSource]){if($null -ne $row.($map.column)){[void]$collected.Add([int]$row.($map.column))}}
                    }
                    $values=@($collected|Sort-Object)
                }else{throw 'Unknown report parameter scope'}
                if($values.Count -gt $method.limits.max_scope_ids -and $key -ne 'label_ids'){throw 'Report scope exceeds limit'}
                $scopes[$key]=$values
            }
        }
        $result=Read-GraphSource $session $method $source.Name $scopes
        $tables[$source.Name]=$result.rows
        $checks[$source.Name]=[ordered]@{complete=$true;row_count=$result.rows.Count;pages=$result.pages;hash_capture=(Get-OaHash $result.rows);scope_counts=$result.scope_counts}
    }
    return [pscustomobject]@{tables=$tables;checks=$checks}
}
try {
    if(Test-Path -LiteralPath $OutputPath){throw 'Output exists'}
    if($seed.category -cne 'B01' -or $seed.business_rows_read -ne 0 -or -not $seed.tables.workflow_base.Count -or $relations.category -cne 'B06' -or $relations.business_rows_read -ne 0 -or $relations.reference_graph.closed -ne $true){throw 'Invalid report dependency'}
    $stage='connection';$session=Open-OaSession $ConnectionDirectory $method.limits.read_budget_seconds
    $identity=[ordered]@{server=$session.Profile.server;port=$session.Profile.port;database=$session.Identity.database_name;server_identity=$session.Identity.server_identity;server_version=$session.Identity.server_version;login=$session.Identity.original_login;database_user=$session.Identity.database_user}
    $stage='dependency'
    if((Get-OaHash $identity) -cne (Get-OaHash $seed.source_identity) -or (Get-OaHash $identity) -cne (Get-OaHash $relations.source_identity) -or (Get-OaHash (Get-WorkflowAnchor)) -cne (Get-OaHash $seed.tables.workflow_base)){throw 'Report source or workflow mismatch'}
    $stage='schema';$schema=Get-GraphSchema $session $method
    $stage='first_pass';$first=Read-ReportPass
    $stage='second_pass';$second=Read-ReportPass
    $stage='consistency'
    if((Get-OaHash $schema) -cne (Get-OaHash (Get-GraphSchema $session $method)) -or (Get-OaHash (Get-WorkflowAnchor)) -cne (Get-OaHash $seed.tables.workflow_base)){throw 'Report schema or workflow changed'}
    foreach($name in $first.tables.Keys){
        $currentSource=$name;$h1=$first.checks[$name].hash_capture;$h2=$second.checks[$name].hash_capture
        if($h1 -cne $h2){throw 'Report configuration changed'}
        $first.checks[$name]['hash_first']=$h1;$first.checks[$name]['hash_second']=$h2
    }
    $stage='save'
    $hashes=[ordered]@{reader=(Get-FileHash $PSCommandPath).Hash;session=(Get-FileHash (Join-Path $PSScriptRoot 'SqlSession.ps1')).Hash;registry=(Get-FileHash (Join-Path $homeDirectory 'registry/B07.json')).Hash;queries=(Get-FileHash (Join-Path $PSScriptRoot 'GraphQueries.ps1')).Hash;scopes=(Get-FileHash (Join-Path $PSScriptRoot 'ReportScopes.ps1')).Hash}
    Write-OaCapture $OutputPath ([ordered]@{format_version=1;category='B07';method_version=$method.method_version;scope=$method.scope;started_at=$started;ended_at=[DateTimeOffset]::UtcNow.ToString('o');source_identity=$identity;business_rows_read=0;transport=[ordered]@{encrypt=$true;trust_server_certificate=$session.Profile.trust_server_certificate};dependency_sha256=(Get-FileHash $DependencyPath).Hash;relation_dependency_sha256=(Get-FileHash $RelationDependencyPath).Hash;schema=$schema;tables=$first.tables;checks=$first.checks;implementation_hashes=$hashes;consistency='two equal sequential definition reads; not a transaction snapshot';permission_audit='selected SELECT plus broad-role checks only; no write test'})
    '{"status":"captured","category":"B07","business_rows_read":0}'
}catch{
    $failure=[ordered]@{status='failed';stage=$stage;source=$currentSource;failure_code='reader_error';business_rows_read=0}
    $ex=$_.Exception
    while($null -ne $ex){if($ex.PSObject.Properties.Name -contains 'Number'){$failure['sql_error_number']=$ex.Number};$ex=$ex.InnerException}
    try{Write-OaCapture (Join-Path (Split-Path $OutputPath -Parent) 'checks.json') ([ordered]@{failure=$failure;first_checks=if($null -ne $first){$first.checks}else{$null};second_checks=if($null -ne $second){$second.checks}else{$null}})}catch{}
    $failure|ConvertTo-Json -Depth 5 -Compress;exit 1
}finally{Close-OaSession $session}
