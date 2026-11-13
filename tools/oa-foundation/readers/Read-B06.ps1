[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$ConnectionDirectory,
      [Parameter(Mandatory=$true)][string]$DependencyPath,
      [Parameter(Mandatory=$true)][string]$OutputPath,
      [Parameter(Mandatory=$true)][string]$PythonExecutable)
. (Join-Path $PSScriptRoot 'SqlSession.ps1')
. (Join-Path $PSScriptRoot 'GraphQueries.ps1')
. (Join-Path $PSScriptRoot 'GraphMetadata.ps1')
$ErrorActionPreference='Stop'
$homeDirectory=Split-Path $PSScriptRoot -Parent
$method=Get-Content (Join-Path $homeDirectory 'registry/B06.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$seed=Get-Content -LiteralPath $DependencyPath -Raw -Encoding UTF8 | ConvertFrom-Json
$session=$null;$stage='initialization';$currentSource=$null;$first=$null;$second=$null
$started=[DateTimeOffset]::UtcNow.ToString('o');$workspaceDirectory=Split-Path $OutputPath -Parent
function Get-WorkflowAnchor {
    $r=Get-Content (Join-Path $homeDirectory 'registry/B01.json') -Raw -Encoding UTF8|ConvertFrom-Json
    $fields=($r.tables.workflow_base.PSObject.Properties.Name|ForEach-Object {'['+$_+']'}) -join ','
    return ,(Read-OaPages $session ('SELECT '+$fields+' FROM dbo.workflow_base') 'id' 20000).rows
}
function Read-ReferencePass {
    $tables=[ordered]@{};$checks=[ordered]@{};$iterations=[Collections.Generic.List[object]]::new()
    $warnings=[Collections.Generic.List[object]]::new();$token=[guid]::NewGuid().ToString('N')
    function Save-GraphSource {
        param([string]$Name,[hashtable]$Scopes=@{})
        $result=Read-GraphSource $session $method $Name $Scopes
        $tables[$Name]=$result.rows
        $checks[$Name]=[ordered]@{complete=$true;row_count=$result.rows.Count;pages=$result.pages;hash_capture=(Get-OaHash $result.rows);scope_counts=$result.scope_counts}
    }
    foreach($source in $method.sources.PSObject.Properties){
        $tables[$source.Name]=@()
        if($source.Value.PSObject.Properties.Name -contains 'role' -and $source.Value.role -eq 'anchor'){Save-GraphSource $source.Name}
    }
    $formIds=[Collections.Generic.HashSet[int]]::new();$codes=[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    $modelIds=[Collections.Generic.HashSet[int]]::new();$customIds=[Collections.Generic.HashSet[int]]::new()
    $settingIds=[Collections.Generic.HashSet[int]]::new();$tableNames=[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    foreach($w in $seed.tables.workflow_base){if([string]$w.isbill -eq '1'){[void]$formIds.Add([int]$w.formid)}}
    Add-GraphCodes $codes $tables['B02_workflow_billfield']
    Add-GraphCodes $codes $tables['B02_workflow_formdict']
    Add-GraphCodes $codes $tables['B02_workflow_formdictdetail']
    foreach($row in $tables['B05_workflow_addinoperate']){
        $raw=[string]$row.wftomodesetid
        if([string]::IsNullOrWhiteSpace($raw)){continue}
        $parts=@([regex]::Split($raw.Trim(),'[,;\s]+')|Where-Object {$_})
        $valid=$true;$numbers=@()
        foreach($part in $parts){$number=0;if(-not [int]::TryParse($part,[ref]$number) -or $number -lt 0){$valid=$false;break};if($number -gt 0){$numbers+=$number}}
        if($valid){foreach($number in $numbers){[void]$settingIds.Add([int]$number)}}
        else{$warnings.Add([pscustomobject]@{kind='setting_reference_syntax_unknown';source='B05_workflow_addinoperate';id=$row.id})}
    }
    Save-GraphSource 'mode_workflowtomodeset' @{setting_ids=@($settingIds|Sort-Object -CaseSensitive)}
    Add-GraphIntegers $settingIds $tables['mode_workflowtomodeset'] 'id' -PositiveOnly
    Add-GraphIntegers $modelIds $tables['mode_workflowtomodeset'] 'modeid' -PositiveOnly
    Save-GraphSource 'mode_workflowtomodesetdetail' @{setting_ids=@($settingIds|Sort-Object -CaseSensitive)}
    Save-GraphSource 'mode_workflowtomodesetopt' @{setting_ids=@($settingIds|Sort-Object -CaseSensitive)}
    function Scope-Fingerprint {
        return Get-OaHash ([ordered]@{forms=@($formIds|Sort-Object -CaseSensitive);codes=@($codes|Sort-Object -CaseSensitive);models=@($modelIds|Sort-Object -CaseSensitive);customs=@($customIds|Sort-Object -CaseSensitive);settings=@($settingIds|Sort-Object -CaseSensitive);tables=@($tableNames|Sort-Object -CaseSensitive)})
    }
    $closed=$false;$sqlEvidence=$null
    for($round=0;$round -lt $method.limits.max_graph_iterations;$round++){
        $before=Scope-Fingerprint
        Save-GraphSource 'MODE_BROWSER' @{codes=@($codes|Sort-Object -CaseSensitive)}
        Save-GraphSource 'datashowset' @{codes=@($codes|Sort-Object -CaseSensitive)}
        Add-GraphIntegers $customIds $tables['MODE_BROWSER'] 'customid' -PositiveOnly
        Add-GraphIntegers $customIds $tables['datashowset'] 'customid' -PositiveOnly
        Save-GraphSource 'mode_custombrowser' @{custom_ids=@($customIds|Sort-Object -CaseSensitive)}
        Save-GraphSource 'mode_CustombrowserDspField' @{custom_ids=@($customIds|Sort-Object -CaseSensitive)}
        Add-GraphIntegers $modelIds $tables['mode_custombrowser'] 'modeid' -PositiveOnly
        Save-GraphSource 'modeinfo' @{mode_ids=@($modelIds|Sort-Object -CaseSensitive)}
        Add-GraphIntegers $formIds $tables['mode_custombrowser'] 'formid'
        Add-GraphIntegers $formIds $tables['modeinfo'] 'formid'
        Save-GraphSource 'workflow_bill' @{form_ids=@($formIds|Sort-Object -CaseSensitive);table_names=@($tableNames|Sort-Object -CaseSensitive)}
        Add-GraphIntegers $formIds $tables['workflow_bill'] 'id'
        Save-GraphSource 'workflow_billfield' @{form_ids=@($formIds|Sort-Object -CaseSensitive)}
        Save-GraphSource 'Workflow_billdetailtable' @{form_ids=@($formIds|Sort-Object -CaseSensitive)}
        Add-GraphCodes $codes $tables['workflow_billfield']
        $standardIds=[Collections.Generic.HashSet[int]]::new()
        $browserFields=@($tables['workflow_billfield']|Where-Object {[string]$_.fieldhtmltype -eq '3'})
        Add-GraphIntegers $standardIds $browserFields 'type' -PositiveOnly
        foreach($legacyName in @('B02_workflow_formdict','B02_workflow_formdictdetail')){
            $legacyBrowserFields=@($tables[$legacyName]|Where-Object {[string]$_.fieldhtmltype -eq '3'})
            Add-GraphIntegers $standardIds $legacyBrowserFields 'type' -PositiveOnly
        }
        Save-GraphSource 'workflow_browserurl' @{type_ids=@($standardIds|Sort-Object -CaseSensitive)}
        $categoryIds=[Collections.Generic.HashSet[int]]::new()
        Add-GraphIntegers $categoryIds $tables['workflow_browserurl'] 'typeid' -PositiveOnly
        Save-GraphSource 'workflow_browsertype' @{type_ids=@($categoryIds|Sort-Object -CaseSensitive)}
        $scanInputs=[Collections.Generic.List[object]]::new()
        foreach($name in @('MODE_BROWSER','datashowset')){
            foreach($row in $tables[$name]){
                foreach($field in @('sqltext','sqltext1','sqltext2','searchById','searchByName')){
                    if($row.$field){$scanInputs.Add([pscustomobject]@{source=$name;source_id=$row.id;field=$field;text=[string]$row.$field;kind='sql';unverified_datasource=(-not [string]::IsNullOrWhiteSpace([string]$row.datasourceid))})}
                }
            }
        }
        foreach($row in $tables['mode_custombrowser']){
            foreach($field in @('defaultsql','conditionsql')){
                if($row.$field){$scanInputs.Add([pscustomobject]@{source='mode_custombrowser';source_id=$row.id;field=$field;text=[string]$row.$field;kind='sql';unverified_datasource=$false})}
            }
        }
        $queries=@{}
        foreach($q in $tables['B05_workflow_datainput_main']){$queries[[int]$q.id]=$q}
        foreach($row in $tables['B05_workflow_datainput_table']){
            $query=$queries[[int]$row.DataInputID]
            $external=$null -eq $query -or -not [string]::IsNullOrWhiteSpace([string]$query.datasourcename)
            if($row.TableName){$scanInputs.Add([pscustomobject]@{source='B05_workflow_datainput_table';source_id=$row.id;field='TableName';text=[string]$row.TableName;kind='identifier';unverified_datasource=$external})}
        }
        foreach($row in $tables['workflow_bill']){
            foreach($field in @('tablename','detailtablename')){
                if($row.$field){$scanInputs.Add([pscustomobject]@{source='workflow_bill';source_id=$row.id;field=$field;text=[string]$row.$field;kind='identifier';unverified_datasource=$false})}
            }
        }
        foreach($entry in @(@{name='Workflow_billdetailtable';field='tablename'},@{name='workflow_billfield';field='detailtable'},@{name='workflow_browserurl';field='tablename'},@{name='mode_workflowtomodesetopt';field='detailtablename'})){
            foreach($row in $tables[$entry.name]){
                if($row.($entry.field)){$scanInputs.Add([pscustomobject]@{source=$entry.name;source_id=$row.id;field=$entry.field;text=[string]$row.($entry.field);kind='identifier';unverified_datasource=$false})}
            }
        }
        if($tables['B02_workflow_formbase'].Count){
            foreach($oldTable in @('workflow_form','workflow_formdetail')){$scanInputs.Add([pscustomobject]@{source='legacy_form';source_id=$null;field='tablename';text=$oldTable;kind='identifier';unverified_datasource=$false})}
        }
        $inputFile=Join-Path $workspaceDirectory ($token+'-'+$round+'-refs-input.json')
        $outputFile=Join-Path $workspaceDirectory ($token+'-'+$round+'-refs-output.json')
        $errorFile=Join-Path $workspaceDirectory ($token+'-'+$round+'-refs-stderr.txt')
        Write-OaCapture $inputFile $scanInputs.ToArray()
        & $PythonExecutable (Join-Path $homeDirectory 'sql_refs.py') $inputFile $outputFile $session.Profile.database 2>$errorFile | Out-Null
        if($LASTEXITCODE -ne 0 -or -not(Test-Path -LiteralPath $outputFile)){throw 'Static reference scan failed'}
        $sqlEvidence=Get-Content -LiteralPath $outputFile -Raw -Encoding UTF8|ConvertFrom-Json
        foreach($table in $sqlEvidence.local_object_names){[void]$tableNames.Add([string]$table)}
        if($formIds.Count -gt $method.limits.max_forms -or $codes.Count -gt $method.limits.max_codes -or $modelIds.Count -gt $method.limits.max_models -or $settingIds.Count -gt $method.limits.max_settings -or $tableNames.Count -gt $method.limits.max_physical_tables){throw 'Graph scope limit exceeded'}
        $after=Scope-Fingerprint
        $iterations.Add([pscustomobject]@{iteration=$round;form_ids=$formIds.Count;browser_codes=$codes.Count;model_ids=$modelIds.Count;custom_ids=$customIds.Count;local_object_candidates=$tableNames.Count;scope_sha256=$after})
        if($before -ceq $after){$closed=$true;break}
    }
    if(-not $closed){throw 'Reference graph did not close within registered limit'}
    Save-GraphSource 'workflow_SelectItem' @{form_ids=@($formIds|Sort-Object -CaseSensitive)}
    $labels=[Collections.Generic.HashSet[int]]::new()
    Add-GraphIntegers $labels $tables['workflow_bill'] 'namelabel'
    Add-GraphIntegers $labels $tables['workflow_billfield'] 'fieldlabel'
    Add-GraphIntegers $labels $tables['mode_CustombrowserDspField'] 'shownamelabel'
    Add-GraphIntegers $labels $tables['workflow_browserurl'] 'labelid'
    Add-GraphIntegers $labels $tables['workflow_browsertype'] 'LABELID'
    Save-GraphSource 'HtmlLabelInfo' @{label_ids=@($labels|Sort-Object -CaseSensitive)}
    $companyIds=[Collections.Generic.HashSet[int]]::new()
    Add-GraphIntegers $companyIds $tables['modeinfo'] 'subcompanyid' -PositiveOnly
    Save-GraphSource 'HrmSubCompany' @{company_ids=@($companyIds|Sort-Object -CaseSensitive)}
    $physical=Read-GraphPhysicalMetadata $session $method @($tableNames|Sort-Object -CaseSensitive)
    foreach($name in $method.metadata_sources){
        $tables[$name]=$physical.$name
        $checks[$name]=[ordered]@{complete=$true;row_count=$physical.$name.Count;pages=@();hash_capture=(Get-OaHash $physical.$name)}
    }
    return [pscustomobject]@{tables=$tables;checks=$checks;reference_graph=[ordered]@{closed=$closed;iterations=$iterations.ToArray();scope_warnings=$warnings.ToArray();sql_reference_evidence=$sqlEvidence;physical_names=@($tableNames|Sort-Object -CaseSensitive)}}
}
try {
    if(Test-Path -LiteralPath $OutputPath){throw 'Output exists'}
    if($seed.category -cne 'B01' -or $seed.business_rows_read -ne 0 -or -not $seed.tables.workflow_base.Count){throw 'Invalid workflow dependency'}
    $stage='connection';$session=Open-OaSession $ConnectionDirectory $method.limits.read_budget_seconds
    $identity=[ordered]@{server=$session.Profile.server;port=$session.Profile.port;database=$session.Identity.database_name;server_identity=$session.Identity.server_identity;server_version=$session.Identity.server_version;login=$session.Identity.original_login;database_user=$session.Identity.database_user}
    $stage='dependency'
    if((Get-OaHash $identity) -cne (Get-OaHash $seed.source_identity) -or (Get-OaHash (Get-WorkflowAnchor)) -cne (Get-OaHash $seed.tables.workflow_base)){throw 'Workflow dependency mismatch'}
    $stage='schema';$schema=Get-GraphSchema $session $method
    $stage='first_pass';$first=Read-ReferencePass
    $stage='second_pass';$second=Read-ReferencePass
    $stage='consistency'
    if((Get-OaHash $schema) -cne (Get-OaHash (Get-GraphSchema $session $method)) -or (Get-OaHash (Get-WorkflowAnchor)) -cne (Get-OaHash $seed.tables.workflow_base)){throw 'Schema or workflow changed'}
    foreach($name in $first.tables.Keys){
        $currentSource=$name;$h1=$first.checks[$name].hash_capture;$h2=$second.checks[$name].hash_capture
        if($h1 -cne $h2){throw 'Reference configuration changed'}
        $first.checks[$name]['hash_first']=$h1;$first.checks[$name]['hash_second']=$h2
    }
    if((Get-OaHash $first.reference_graph) -cne (Get-OaHash $second.reference_graph)){throw 'Reference graph changed'}
    $stage='save'
    $hashes=[ordered]@{reader=(Get-FileHash $PSCommandPath).Hash;session=(Get-FileHash (Join-Path $PSScriptRoot 'SqlSession.ps1')).Hash;registry=(Get-FileHash (Join-Path $homeDirectory 'registry/B06.json')).Hash;queries=(Get-FileHash (Join-Path $PSScriptRoot 'GraphQueries.ps1')).Hash;metadata=(Get-FileHash (Join-Path $PSScriptRoot 'GraphMetadata.ps1')).Hash;sql_refs=(Get-FileHash (Join-Path $homeDirectory 'sql_refs.py')).Hash}
    Write-OaCapture $OutputPath ([ordered]@{format_version=1;category='B06';method_version=$method.method_version;scope=$method.scope;started_at=$started;ended_at=[DateTimeOffset]::UtcNow.ToString('o');source_identity=$identity;business_rows_read=0;transport=[ordered]@{encrypt=$true;trust_server_certificate=$session.Profile.trust_server_certificate};dependency_sha256=(Get-FileHash $DependencyPath).Hash;schema=$schema;tables=$first.tables;checks=$first.checks;reference_graph=$first.reference_graph;implementation_hashes=$hashes;consistency='two equal sequential graph and metadata reads; not a transaction snapshot';permission_audit='selected SELECT plus broad-role checks only; no write test'})
    '{"status":"captured","category":"B06","business_rows_read":0}'
} catch {
    $failure=[ordered]@{status='failed';stage=$stage;source=$currentSource;failure_code='reader_error';business_rows_read=0}
    $ex=$_.Exception
    while($null -ne $ex){if($ex.PSObject.Properties.Name -contains 'Number'){$failure['sql_error_number']=$ex.Number};$ex=$ex.InnerException}
    try {Write-OaCapture (Join-Path $workspaceDirectory 'checks.json') ([ordered]@{failure=$failure;first_checks=if($null -ne $first){$first.checks}else{$null};second_checks=if($null -ne $second){$second.checks}else{$null}})}catch{}
    $failure|ConvertTo-Json -Depth 5 -Compress
    exit 1
} finally {Close-OaSession $session}
