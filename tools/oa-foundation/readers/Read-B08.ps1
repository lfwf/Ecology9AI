[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$ConnectionDirectory,
      [Parameter(Mandatory=$true)][string]$DependencyPath,
      [Parameter(Mandatory=$true)][string]$RelationDependencyPath,
      [Parameter(Mandatory=$true)][string]$ReportDependencyPath,
      [Parameter(Mandatory=$true)][string]$OutputPath)
. (Join-Path $PSScriptRoot 'SqlSession.ps1')
. (Join-Path $PSScriptRoot 'GraphQueries.ps1')
. (Join-Path $PSScriptRoot 'InterfaceScopes.ps1')
$ErrorActionPreference='Stop';$homeDirectory=Split-Path $PSScriptRoot -Parent
$method=Get-Content (Join-Path $homeDirectory 'registry/B08.json') -Raw -Encoding UTF8|ConvertFrom-Json
$seed=Get-Content -LiteralPath $DependencyPath -Raw -Encoding UTF8|ConvertFrom-Json
$relations=Get-Content -LiteralPath $RelationDependencyPath -Raw -Encoding UTF8|ConvertFrom-Json
$reports=Get-Content -LiteralPath $ReportDependencyPath -Raw -Encoding UTF8|ConvertFrom-Json
$session=$null;$first=$null;$second=$null;$stage='initialization';$currentSource=$null
$started=[DateTimeOffset]::UtcNow.ToString('o')
function Get-WorkflowAnchor {
    $r=Get-Content (Join-Path $homeDirectory 'registry/B01.json') -Raw -Encoding UTF8|ConvertFrom-Json
    $fields=($r.tables.workflow_base.PSObject.Properties.Name|ForEach-Object {'['+$_+']'}) -join ','
    return ,(Read-OaPages $session ('SELECT '+$fields+' FROM dbo.workflow_base') 'id' 20000).rows
}
function Read-InterfacePass {
    $tables=[ordered]@{};$checks=[ordered]@{};$script:scopeWarnings=[Collections.Generic.List[object]]::new()
    $initial=@{
       mode_ids=@($relations.tables.modeinfo|ForEach-Object {[int]$_.id})
       form_ids=@($relations.tables.workflow_bill|ForEach-Object {[int]$_.id})
       label_ids=@($relations.tables.HtmlLabelInfo|ForEach-Object {[int]$_.indexid}|Sort-Object -Unique)
       report_mode_ids=@($reports.tables.modeinfo|ForEach-Object {[int]$_.id})
       all_mode_ids=@(@($relations.tables.modeinfo)+@($reports.tables.modeinfo)|ForEach-Object {[int]$_.id}|Sort-Object -Unique)
    }
    function Save-Source {
        param([string]$Name)
        $scopes=Get-InterfaceScopes $method $Name $tables $initial
        $result=Read-GraphSource $session $method $Name $scopes
        $tables[$Name]=$result.rows
        $checks[$Name]=[ordered]@{complete=$true;row_count=$result.rows.Count;pages=$result.pages;hash_capture=(Get-OaHash $result.rows);scope_counts=$result.scope_counts}
    }
    foreach($source in $method.sources.PSObject.Properties){
        if($source.Value.PSObject.Properties.Name -contains 'role' -and $source.Value.role -eq 'anchor'){Save-Source $source.Name}
    }
    foreach($name in @('workflowactionset','modeinfo','mode_pageexpand')){Save-Source $name}
    $rootIds=[Collections.Generic.HashSet[int]]::new()
    Add-GraphIntegers $rootIds $tables['mode_pageexpand'] 'id' -PositiveOnly
    $parents=[Collections.Generic.HashSet[int]]::new()
    foreach($row in $tables['mode_pageexpand']){if($row.mainid -gt 0 -and -not $rootIds.Contains([int]$row.mainid)){[void]$parents.Add([int]$row.mainid)}}
    $iterations=[Collections.Generic.List[object]]::new();$closed=$false
    for($round=0;$round -lt $method.limits.max_parent_iterations;$round++){
        $before=Get-OaHash @($parents|Sort-Object);$initial['parent_ids']=@($parents|Sort-Object)
        Save-Source 'mode_pageexpand_parent'
        foreach($row in $tables['mode_pageexpand_parent']){if($row.mainid -gt 0 -and -not $rootIds.Contains([int]$row.mainid)){[void]$parents.Add([int]$row.mainid)}}
        if(($parents.Count+$rootIds.Count) -gt $method.limits.max_expands){throw 'Expand reference scope cap exceeded'}
        $after=Get-OaHash @($parents|Sort-Object)
        $iterations.Add([pscustomobject]@{iteration=$round;root_expands=$rootIds.Count;parent_ids=$parents.Count;scope_sha256=$after})
        if($before -ceq $after){$closed=$true;break}
    }
    if(-not $closed){throw 'Expand parent reference scope did not close'}
    $initial['parent_ids']=@($parents|Sort-Object)
    $initial['expand_ids']=@(@($rootIds)+@($parents)|Sort-Object -Unique)
    $skip=@('workflowactionset','modeinfo','mode_pageexpand','mode_pageexpand_parent')
    foreach($source in $method.sources.PSObject.Properties){
        if($source.Value.PSObject.Properties.Name -contains 'role' -and $source.Value.role -eq 'anchor'){continue}
        if($source.Name -in $skip){continue}
        Save-Source $source.Name
    }
    return [pscustomobject]@{tables=$tables;checks=$checks;reference_graph=[ordered]@{closed=$closed;iterations=$iterations.ToArray();scope_warnings=$script:scopeWarnings.ToArray()}}
}
try{
    if(Test-Path -LiteralPath $OutputPath){throw 'Output exists'}
    foreach($dep in @($seed,$relations,$reports)){if($dep.business_rows_read -ne 0 -or $null -eq $dep.source_identity){throw 'Invalid configuration dependency'}}
    if($seed.category -cne 'B01' -or $relations.category -cne 'B06' -or $reports.category -cne 'B07' -or -not $seed.tables.workflow_base.Count){throw 'Dependency category mismatch'}
    $stage='connection';$session=Open-OaSession $ConnectionDirectory $method.limits.read_budget_seconds
    $identity=[ordered]@{server=$session.Profile.server;port=$session.Profile.port;database=$session.Identity.database_name;server_identity=$session.Identity.server_identity;server_version=$session.Identity.server_version;login=$session.Identity.original_login;database_user=$session.Identity.database_user}
    $stage='dependency'
    foreach($dep in @($seed,$relations,$reports)){if((Get-OaHash $identity) -cne (Get-OaHash $dep.source_identity)){throw 'Source identity mismatch'}}
    if((Get-OaHash (Get-WorkflowAnchor)) -cne (Get-OaHash $seed.tables.workflow_base)){throw 'Workflow scope changed'}
    $stage='schema';$schema=Get-GraphSchema $session $method
    $stage='first_pass';$first=Read-InterfacePass
    $stage='second_pass';$second=Read-InterfacePass
    $stage='consistency'
    if((Get-OaHash $schema) -cne (Get-OaHash (Get-GraphSchema $session $method)) -or (Get-OaHash (Get-WorkflowAnchor)) -cne (Get-OaHash $seed.tables.workflow_base)){throw 'Schema or workflow changed'}
    foreach($name in $first.tables.Keys){
        $currentSource=$name;$h1=$first.checks[$name].hash_capture;$h2=$second.checks[$name].hash_capture
        if($h1 -cne $h2){throw 'Interface configuration changed'}
        $first.checks[$name]['hash_first']=$h1;$first.checks[$name]['hash_second']=$h2
    }
    if((Get-OaHash $first.reference_graph) -cne (Get-OaHash $second.reference_graph)){throw 'Interface scope changed'}
    $hashes=[ordered]@{reader=(Get-FileHash $PSCommandPath).Hash;session=(Get-FileHash (Join-Path $PSScriptRoot 'SqlSession.ps1')).Hash;registry=(Get-FileHash (Join-Path $homeDirectory 'registry/B08.json')).Hash;queries=(Get-FileHash (Join-Path $PSScriptRoot 'GraphQueries.ps1')).Hash;scopes=(Get-FileHash (Join-Path $PSScriptRoot 'InterfaceScopes.ps1')).Hash}
    $stage='save'
    Write-OaCapture $OutputPath ([ordered]@{format_version=1;category='B08';method_version=$method.method_version;scope=$method.scope;started_at=$started;ended_at=[DateTimeOffset]::UtcNow.ToString('o');source_identity=$identity;business_rows_read=0;transport=[ordered]@{encrypt=$true;trust_server_certificate=$session.Profile.trust_server_certificate};dependency_sha256=(Get-FileHash $DependencyPath).Hash;relation_dependency_sha256=(Get-FileHash $RelationDependencyPath).Hash;report_dependency_sha256=(Get-FileHash $ReportDependencyPath).Hash;schema=$schema;tables=$first.tables;checks=$first.checks;reference_graph=$first.reference_graph;implementation_hashes=$hashes;consistency='two equal sequential definition and reference reads; not a transaction snapshot';permission_audit='selected SELECT plus broad-role checks only; no write test'})
    '{"status":"captured","category":"B08","business_rows_read":0}'
}catch{
    $failure=[ordered]@{status='failed';stage=$stage;source=$currentSource;failure_code='reader_error';business_rows_read=0}
    $ex=$_.Exception;while($null -ne $ex){if($ex.PSObject.Properties.Name -contains 'Number'){$failure['sql_error_number']=$ex.Number};$ex=$ex.InnerException}
    try{Write-OaCapture (Join-Path (Split-Path $OutputPath -Parent) 'checks.json') ([ordered]@{failure=$failure;first_checks=if($null -ne $first){$first.checks}else{$null};second_checks=if($null -ne $second){$second.checks}else{$null}})}catch{}
    $failure|ConvertTo-Json -Depth 5 -Compress;exit 1
}finally{Close-OaSession $session}
