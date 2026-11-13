import json,shutil,subprocess,unittest
from pathlib import Path
class MetadataReaderTests(unittest.TestCase):
    def test_empty_result_still_has_native_column_contract(self):
        shell=shutil.which('powershell')
        if not shell:self.skipTest('PowerShell unavailable')
        home=Path(__file__).resolve().parents[1]
        script=r"""
$ErrorActionPreference='Stop'
. 'HOME/readers/MetadataQueries.ps1'
$script:fakeTable=[Data.DataTable]::new()
[void]$script:fakeTable.Columns.Add('id',[int]);[void]$script:fakeTable.Columns.Add('label',[string])
$script:fakeCommand=[pscustomobject]@{CommandText='';CommandTimeout=0}
$script:fakeCommand|Add-Member ScriptMethod ExecuteReader {return ,$script:fakeTable.CreateDataReader()}
$script:fakeCommand|Add-Member ScriptMethod Dispose {}
$conn=[pscustomobject]@{}
$conn|Add-Member ScriptMethod CreateCommand {return $script:fakeCommand}
$session=[pscustomobject]@{Connection=$conn;Clock=[Diagnostics.Stopwatch]::StartNew();Budget=30}
$r=Read-MetadataSource $session 'SELECT metadata_only' @{} 20
[ordered]@{rows=$r.rows.Count;contract=@($r.contract|ForEach-Object {$_.column_name});types=@($r.contract|ForEach-Object {$_.data_type})}|ConvertTo-Json -Compress
""".replace('HOME',str(home).replace('\\','/').replace("'","''"))
        p=subprocess.run([shell,'-NoLogo','-NoProfile','-NonInteractive','-Command',script],capture_output=True)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(json.loads(p.stdout),{'rows':0,'contract':['id','label'],'types':['System.Int32','System.String']})
    def test_registered_queries_have_no_business_from_or_join(self):
        import sys,re
        home=Path(__file__).resolve().parents[1]
        m=json.loads((home/'registry/B09.json').read_text('utf-8'))
        for name,source in m['metadata_queries'].items():
            sql=source['sql']
            references=re.findall(r'\b(?:FROM|JOIN)\s+([^\s]+)',sql,re.I)
            self.assertTrue(references,name)
            self.assertTrue(all(x.casefold().startswith('sys.') for x in references),(name,references))
            self.assertNotRegex(sql,r'(?i)\b(?:EXEC|INSERT|UPDATE|DELETE|MERGE|CREATE|ALTER|DROP)\b')
