import json,shutil,subprocess,unittest
from pathlib import Path
HOME=Path(__file__).resolve().parents[1]
class GraphQueryTests(unittest.TestCase):
    def test_typed_scope_parameters_keep_negative_ids_and_quote_strings(self):
        helper=str(HOME/'readers/GraphQueries.ps1').replace("'","''")
        session=str(HOME/'readers/SqlSession.ps1').replace("'","''")
        code=r"""
$ErrorActionPreference='Stop'
. '__SESSION__'
. '__HELPER__'
$method=([pscustomobject]@{sources=[pscustomobject]@{sample=[pscustomobject]@{sql='SELECT id FROM dbo.modeinfo WHERE formid IN ({form_ids}) AND name IN ({codes})';order_by='id';row_cap=100;scope_types=[pscustomobject]@{form_ids='int';codes='string'}}}})
function Read-OaPages {
 param($Session,[string]$Sql,[string]$Order,[int]$Cap,[hashtable]$Parameters)
 if($Sql -like '*DROP*' -or $Sql -like '*{*'){throw 'Unsafe interpolation'}
 if(@($Parameters.Values|Where-Object {$_ -is [int] -and $_ -eq -7}).Count -ne 1){throw 'Signed form id lost'}
 if(@($Parameters.Values|Where-Object {$_ -eq "x'); DROP TABLE data;--"}).Count -ne 1){throw 'String not passed as data'}
 return [pscustomobject]@{rows=@([pscustomobject]@{id=1});pages=@([pscustomobject]@{row_count=1});complete=$true}
}
$r=Read-GraphSource $null $method 'sample' @{form_ids=@(-7);codes=@("x'); DROP TABLE data;--")}
$invalid=$false
try{Read-GraphSource $null $method 'sample' @{form_ids=@('7 OR 1=1');codes=@('x')}|Out-Null}catch{$invalid=$true}
$empty=Read-GraphSource $null $method 'sample' @{form_ids=@();codes=@()}
[ordered]@{rows=$r.rows.Count;invalid_scope_rejected=$invalid;empty_rows=$empty.rows.Count}|ConvertTo-Json -Compress
""".replace('__SESSION__',session).replace('__HELPER__',helper)
        r=subprocess.run([shutil.which('pwsh'),'-NoLogo','-NoProfile','-NonInteractive','-Command',code],capture_output=True)
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(json.loads(r.stdout),dict(rows=1,invalid_scope_rejected=True,empty_rows=0))
    def test_large_reference_set_is_partitioned_without_dropping_rows(self):
        helper=str(HOME/'readers/GraphQueries.ps1').replace("'","''");session=str(HOME/'readers/SqlSession.ps1').replace("'","''")
        code=r'''
$ErrorActionPreference='Stop'
. '__SESSION__'
. '__HELPER__'
$method=([pscustomobject]@{sources=[pscustomobject]@{labels=[pscustomobject]@{sql='SELECT indexid FROM dbo.HtmlLabelInfo WHERE indexid IN ({label_ids})';order_by='indexid';row_cap=5;scope_types=[pscustomobject]@{label_ids='int'};partition_scope='label_ids';partition_size=2}}})
function Read-OaPages {
 param($Session,[string]$Sql,[string]$Order,[int]$Cap,[hashtable]$Parameters)
 if($Parameters.Count -gt 2){throw 'Parameter block exceeds declared partition size'}
 $rows=@($Parameters.Values|Sort-Object|ForEach-Object {[pscustomobject]@{indexid=$_}})
 return [pscustomobject]@{rows=$rows;pages=@([pscustomobject]@{row_count=$rows.Count});complete=$true}
}
$r=Read-GraphSource $null $method 'labels' @{label_ids=@(1,2,3,4,5)}
$method.sources.labels.row_cap=4;$cap=$false
try{Read-GraphSource $null $method 'labels' @{label_ids=@(1,2,3,4,5)}|Out-Null}catch{$cap=$true}
[ordered]@{ids=@($r.rows.indexid);pages=$r.pages.Count;cap_rejected=$cap}|ConvertTo-Json -Compress
'''.replace('__SESSION__',session).replace('__HELPER__',helper)
        r=subprocess.run([shutil.which('pwsh'),'-NoLogo','-NoProfile','-NonInteractive','-Command',code],capture_output=True)
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(json.loads(r.stdout),dict(ids=[1,2,3,4,5],pages=3,cap_rejected=True))

    def test_case_distinct_string_references_are_both_queried(self):
        helper=str(HOME/'readers/GraphQueries.ps1').replace("'","''");session=str(HOME/'readers/SqlSession.ps1').replace("'","''")
        code=r'''
$ErrorActionPreference='Stop'
. '__SESSION__'
. '__HELPER__'
$method=[pscustomobject]@{sources=[pscustomobject]@{sample=[pscustomobject]@{sql='SELECT id FROM dbo.MODE_BROWSER WHERE showname IN ({codes})';order_by='id';row_cap=10;scope_types=[pscustomobject]@{codes='string'}}}}
function Read-OaPages {
 param($Session,[string]$Sql,[string]$Order,[int]$Cap,[hashtable]$Parameters)
 return [pscustomobject]@{rows=@($Parameters.Values|Sort-Object -CaseSensitive|ForEach-Object {[pscustomobject]@{code=$_}});pages=@();complete=$true}
}
$r=Read-GraphSource $null $method 'sample' @{codes=@('BrowserA','browsera')}
[ordered]@{codes=@($r.rows.code)}|ConvertTo-Json -Compress
'''.replace('__SESSION__',session).replace('__HELPER__',helper)
        r=subprocess.run([shutil.which('pwsh'),'-NoLogo','-NoProfile','-NonInteractive','-Command',code],capture_output=True)
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(sorted(json.loads(r.stdout)['codes']),['BrowserA','browsera'])

if __name__=='__main__':unittest.main()
