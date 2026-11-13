param([Parameter(Mandatory=$true)][int]$WorkflowId,[Parameter(Mandatory=$true)][string]$ExpectedWorkflowName,[Parameter(Mandatory=$true)][int]$ExpectedFormId,[string]$TaskClass='',[Parameter(Mandatory=$true)][string]$ConnectionDirectory,[Parameter(Mandatory=$true)][string]$OutputPath,[string]$PythonExecutable='python')
$ErrorActionPreference='Stop';$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
. (Join-Path $root 'tools/oa-foundation/readers/SqlSession.ps1')
. (Join-Path $PSScriptRoot 'ScopedPhysical.ps1')
. (Join-Path $PSScriptRoot 'ScopedSchema.ps1')
$session=$null;$stage='prepare';$currentSource=$null
try{
 if(Test-Path -LiteralPath $OutputPath){throw 'Output exists'}
 $specPath=Join-Path (Split-Path $OutputPath -Parent) ('methods-'+[guid]::NewGuid().ToString('N')+'.json')
 $prep=& $PythonExecutable (Join-Path $PSScriptRoot 'scoped_config.py') --workflow $WorkflowId --output $specPath 2>$null
 if($LASTEXITCODE -ne 0){throw 'Specification failed'}
 $spec=Get-Content -LiteralPath $specPath -Raw -Encoding UTF8|ConvertFrom-Json
 $specHash=(Get-FileHash $specPath).Hash
 $stage='connection';$session=Open-OaSession $ConnectionDirectory 600
 $params=@{'@workflow'=$WorkflowId;'@jobclass'=$TaskClass}
 $started=[DateTimeOffset]::UtcNow.ToString('o');$homeDirectory=Join-Path $root 'tools/oa-foundation'
 $fields=((Get-Content (Join-Path $homeDirectory 'registry/B01.json') -Raw -Encoding UTF8|ConvertFrom-Json).tables.workflow_base.PSObject.Properties.Name|ForEach-Object {'['+$_+']'}) -join ','
 $anchorSql='SELECT '+$fields+' FROM dbo.workflow_base WHERE id=@workflow'
 $anchor=Invoke-OaQuery $session $anchorSql $params 1
 if($anchor.Count -ne 1 -or $anchor[0].workflowname -cne $ExpectedWorkflowName -or $anchor[0].formid -ne $ExpectedFormId){throw 'Workflow scope changed'}
 $passes=[Collections.Generic.List[object]]::new()
 for($pass=0;$pass -lt 2;$pass++){
  $categories=[ordered]@{};$schemas=[ordered]@{}
  foreach($entry in $spec.categories.PSObject.Properties){
   $method=$entry.Value;$stage='schema_'+$entry.Name
   $schemas[$entry.Name]=Get-ConfigSchema
   $tables=[ordered]@{};$checks=[ordered]@{}
   foreach($source in $method.sources.PSObject.Properties){
    $currentSource=$entry.Name+':'+$source.Name;$stage='capture_'+$entry.Name
    if($source.Value.PSObject.Properties.Name -contains 'reference_scope'){$result=Read-OaReferencedScope $session $source.Value $tables}
    elseif($source.Value.PSObject.Properties.Name -contains 'partition_by'){$result=Read-OaPartitions $session $source.Value $tables}
    else{$result=Read-OaPages $session $source.Value.sql $source.Value.order_by $source.Value.row_cap $params}
    $tables[$source.Name]=$result.rows
    $checks[$source.Name]=[ordered]@{row_count=$result.rows.Count;complete=$true;hash=(Get-OaHash $result.rows)}
   }
   if($entry.Name -ceq 'B02'){
    $physical=Read-PhysicalMetadata $tables
    foreach($name in $method.metadata_sources){$tables[$name]=$physical.$name;$checks[$name]=[ordered]@{row_count=$physical.$name.Count;complete=$true;hash=(Get-OaHash $physical.$name)}}
   }
   $categories[$entry.Name]=[ordered]@{tables=$tables;checks=$checks}
  }
  $passes.Add([pscustomobject]@{categories=$categories;schemas=$schemas})
 }
 $stage='consistency'
 if((Get-OaHash $passes[0].schemas) -cne (Get-OaHash $passes[1].schemas)){throw 'Schema changed'}
 foreach($cat in $passes[0].categories.Keys){
  foreach($name in $passes[0].categories[$cat].tables.Keys){
   $a=$passes[0].categories[$cat].checks[$name];$b=$passes[1].categories[$cat].checks[$name]
   if($a.hash -cne $b.hash){throw 'Configuration changed'}
   $a['hash_first']=$a.hash;$a['hash_second']=$b.hash
  }
 }
 if((Get-OaHash $anchor) -cne (Get-OaHash (Invoke-OaQuery $session $anchorSql $params 1))){throw 'Anchor changed'}
 if((Get-FileHash $specPath).Hash -cne $specHash){throw 'Method changed'}
 foreach($c in $spec.registry_sha256.PSObject.Properties){if((Get-FileHash (Join-Path $homeDirectory ('registry/'+$c.Name+'.json'))).Hash.ToLowerInvariant() -cne $c.Value){throw 'Registry changed'}}
 $stage='save'
 Write-OaCapture $OutputPath ([ordered]@{source_identity=$session.Identity;started_at=$started;ended_at=[DateTimeOffset]::UtcNow.ToString('o');workflow_id=$WorkflowId;anchor=$anchor;categories=$passes[0].categories;schema=$passes[0].schemas;business_rows_read=0;registry_sha256=$spec.registry_sha256;spec_sha256=$specHash;reader_sha256=(Get-FileHash $PSCommandPath).Hash;consistency='two equal sequential scoped configuration reads, not a transaction snapshot'})
 '{"status":"captured_scoped_configuration","business_rows_read":0}'
}catch{[ordered]@{status='failed';stage=$stage;source=$currentSource}|ConvertTo-Json -Compress;exit 1}finally{Close-OaSession $session}
