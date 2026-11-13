import unittest,subprocess,json,shutil
from pathlib import Path
class ReportScopeTests(unittest.TestCase):
    def test_strict_ascii_csv_keeps_whitespace_and_rejects_internal_digit_spaces(self):
        shell=shutil.which('powershell')
        if not shell:self.skipTest('PowerShell unavailable')
        helper=Path(__file__).resolve().parents[1]/'readers/ReportScopes.ps1'
        cmd=""". 'PATH'; $wf=@([pscustomobject]@{id=1;formid=-14;isbill='1'},[pscustomobject]@{id=12;formid=-15;isbill='1'}); $rows=@(
[pscustomobject]@{id=1;formid=999;isbill='1';wfs='1 2'},
[pscustomobject]@{id=2;formid=999;isbill='1';wfs=('99,'+[char]9+'1')},
[pscustomobject]@{id=3;formid=999;isbill='1';wfs=('99,'+[char]10+'1')},
[pscustomobject]@{id=4;formid=999;isbill='1';wfs='99, 12'},
[pscustomobject]@{id=5;formid=-14;isbill='1';wfs='bad'},
[pscustomobject]@{id=6;formid=14;isbill='0';wfs='1;12'},
[pscustomobject]@{id=7;formid=999;isbill='1';wfs='1,,12'},
[pscustomobject]@{id=8;formid=999;isbill='1';wfs='1,999999999999'});
ConvertTo-Json -InputObject (Select-OaReportScope $rows $wf 'wfs') -Compress""".replace('PATH',str(helper).replace("'","''"))
        r=subprocess.run([shell,'-NoLogo','-NoProfile','-NonInteractive','-Command',cmd],capture_output=True)
        self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(json.loads(r.stdout),[2,3,4,5])

    def test_reader_pass_supplies_flat_typed_selected_ids(self):
        shell=shutil.which('powershell')
        if not shell:self.skipTest('PowerShell unavailable')
        home=Path(__file__).resolve().parents[1]
        cmd=r"""
. 'HOME/readers/ReportScopes.ps1'
$ast=[Management.Automation.Language.Parser]::ParseFile('HOME/readers/Read-B07.ps1',[ref]$null,[ref]$null)
$fn=$ast.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Read-ReportPass'},$true)
Invoke-Expression $fn.Extent.Text
$relations=[pscustomobject]@{tables=[pscustomobject]@{modeinfo=@();workflow_bill=@();HtmlLabelInfo=@()}}
$seed=[pscustomobject]@{tables=[pscustomobject]@{workflow_base=@([pscustomobject]@{id=1;formid=-14;isbill='1'})}}
$method=ConvertFrom-Json '{"sources":{"Workflow_Report_scope":{},"Workflow_Report":{"scope_types":{"selected_standard_ids":"int"}}},"limits":{"max_scope_ids":1600}}'
function Get-OaHash($value){return 'synthetic-hash'}
function Read-GraphSource($session,$method,$name,$scopes){
 if($name -eq 'Workflow_Report_scope'){$rows=@([pscustomobject]@{id=11;formid=-14;isbill='1';reportwfid=''},[pscustomobject]@{id=12;formid=999;isbill='1';reportwfid='1'})}
 else {
   if($scopes.selected_standard_ids.Count -ne 2){throw 'Expected two flat IDs'}
   foreach($id in $scopes.selected_standard_ids){if($id -isnot [int]){throw 'Expected typed scalar IDs'}}
   $rows=@()
 }
 return [pscustomobject]@{rows=$rows;pages=@();scope_counts=@{}}
}
$r=Read-ReportPass
'pass'
""".replace('HOME',str(home).replace("'","''").replace('\\','/'))
        r=subprocess.run([shell,'-NoLogo','-NoProfile','-NonInteractive','-Command',cmd],capture_output=True)
        self.assertEqual(r.returncode,0,r.stderr);self.assertIn(b'pass',r.stdout)
