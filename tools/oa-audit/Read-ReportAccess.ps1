param([Parameter(Mandatory=$true)][string]$OutputPath,[Parameter(Mandatory=$true)][string]$ConnectionDirectory,[Parameter(Mandatory=$true)][int]$ModuleId,[Parameter(Mandatory=$true)][int]$FormId)
$projectRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
. (Join-Path $projectRoot 'tools/oa-foundation/readers/SqlSession.ps1')
$ErrorActionPreference='Stop';$session=$null;$stage='connection'
try{
 $session=Open-OaSession $ConnectionDirectory 60
 $params=@{'@module'=$ModuleId;'@form'=$FormId}
 $t=[ordered]@{};$started=[DateTimeOffset]::UtcNow.ToString('o')
 $stage='list_settings'
 $t.lists=Invoke-OaQuery $session "SELECT id,modeid,formid,norightlist,isupdateenabled,enabled,syncexport FROM dbo.mode_customsearch WHERE (modeid=@module OR formid=@form) ORDER BY id" $params 30
 $stage='sharing'
 $t.sharing=Invoke-OaQuery $session "SELECT pageid,righttype,sharetype,COUNT_BIG(*) AS rule_count FROM dbo.mode_searchPageshareinfo WHERE pageid IN (SELECT id FROM dbo.mode_customsearch WHERE (modeid=@module OR formid=@form)) GROUP BY pageid,righttype,sharetype ORDER BY pageid,righttype,sharetype" $params 100
 $stage='field_settings'
 $t.fields=Invoke-OaQuery $session "SELECT d.customid,d.fieldid,d.isshow,d.isquery,d.editable,d.addable,d.isstat FROM dbo.mode_CustomDspField d WHERE d.customid IN (SELECT id FROM dbo.mode_customsearch WHERE (modeid=@module OR formid=@form)) ORDER BY d.customid,d.fieldid" $params 300
 $stage='field_definitions'
 $t.definitions=Invoke-OaQuery $session "SELECT id,fieldname,fieldlabel,fielddbtype FROM dbo.workflow_billfield WHERE billid=@form ORDER BY id" $params 150
 $stage='report_entry'
 $t.reports=Invoke-OaQuery $session "SELECT id,modeid,formid FROM dbo.mode_report WHERE (modeid=@module OR formid=@form) ORDER BY id" $params 30
 $stage='report_sharing'
 $t.report_sharing=Invoke-OaQuery $session "SELECT reportid,righttype,sharetype,COUNT_BIG(*) AS rule_count FROM dbo.mode_reportshareinfo WHERE reportid IN (SELECT id FROM dbo.mode_report WHERE (modeid=@module OR formid=@form)) GROUP BY reportid,righttype,sharetype ORDER BY reportid,righttype,sharetype" $params 100
 $stage='report_fields'
 $t.report_fields=Invoke-OaQuery $session "SELECT reportid,fieldid,isshow,isstat FROM dbo.mode_ReportDspField WHERE reportid IN (SELECT id FROM dbo.mode_report WHERE (modeid=@module OR formid=@form)) ORDER BY reportid,fieldid" $params 300
 $stage='module_state'
 $t.module_state=Invoke-OaQuery $session "SELECT id,formid,modetype,isdelete FROM dbo.modeinfo WHERE id=@module" $params 1
 $stage='browser_entries'
 $t.browser_entries=Invoke-OaQuery $session "SELECT id,modeid,formid FROM dbo.mode_custombrowser WHERE (modeid=@module OR formid=@form) ORDER BY id" $params 30
 Write-OaCapture $OutputPath ([ordered]@{source_identity=$session.Identity;started_at=$started;ended_at=[DateTimeOffset]::UtcNow.ToString('o');tables=$t;scope='sample report configuration and permission flags only; no business values or identities';reader_sha256=(Get-FileHash $PSCommandPath).Hash})
 '{"status":"captured_config_only"}'
}catch{[ordered]@{status='failed';stage=$stage}|ConvertTo-Json -Compress;exit 1}finally{Close-OaSession $session}
