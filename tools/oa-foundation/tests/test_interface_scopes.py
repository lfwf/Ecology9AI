import json,subprocess,shutil,unittest
from pathlib import Path
class InterfaceScopeTests(unittest.TestCase):
    def test_filtered_reference_keys_are_typed_and_not_confused_with_row_ids(self):
        shell=shutil.which('powershell')
        if not shell:self.skipTest('PowerShell unavailable')
        home=Path(__file__).resolve().parents[1]
        cmd=r"""
. 'HOME/readers/InterfaceScopes.ps1'
$script:scopeWarnings=[Collections.Generic.List[object]]::new()
$m=ConvertFrom-Json '{"sources":{"test":{"scope_types":{"java_names":"string","form_ids":"int"}}},"scope_mappings":{"java_names":{"source":"workflowactionset","column":"interfaceid","filter":{"interfacetype":"3"}}},"limits":{"max_scope_ids":1600,"max_expands":10000}}'
$tables=[ordered]@{workflowactionset=@([pscustomobject]@{id=99;interfacetype='3';interfaceid="REG'NAME"},[pscustomobject]@{id=88;interfacetype='1';interfaceid='2'})}
$initial=@{form_ids=@(-9,14)}
$s=Get-InterfaceScopes $m 'test' $tables $initial
[ordered]@{names=@($s.java_names);forms=@($s.form_ids);warnings=$script:scopeWarnings.Count}|ConvertTo-Json -Compress
""".replace('HOME',str(home).replace('\\','/').replace("'","''"))
        p=subprocess.run([shell,'-NoLogo','-NoProfile','-NonInteractive','-Command',cmd],capture_output=True)
        self.assertEqual(p.returncode,0,p.stderr);d=json.loads(p.stdout)
        self.assertEqual(d,{'names':["REG'NAME"],'forms':[-9,14],'warnings':0})
