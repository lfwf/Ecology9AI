import json,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
HOME=Path(__file__).resolve().parents[1]
class ReferencePassTests(unittest.TestCase):
    def test_custom_negative_labels_survive_actual_graph_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            def quote(x):return str(x).replace("'","''")
            code=r"""
$ErrorActionPreference='Stop'
. '__SESSION__'
. '__QUERIES__'
$ast=[System.Management.Automation.Language.Parser]::ParseFile('__READER__',[ref]$null,[ref]$null)
$function=$ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Read-ReferencePass'},$true)
. ([scriptblock]::Create($function.Extent.Text))
$homeDirectory='__HOME__';$workspaceDirectory='__TEMP__';$PythonExecutable='__PYTHON__'
$method=Get-Content '__REGISTRY__' -Raw|ConvertFrom-Json
$session=[pscustomobject]@{Profile=[pscustomobject]@{database='fixture'}}
$seed=[pscustomobject]@{tables=[pscustomobject]@{workflow_base=@([pscustomobject]@{id=10;isbill='1';formid=-7})}}
$fixtureBill=[pscustomobject]@{id=-7;namelabel=-101;tablename='uf_test';detailtablename=$null}
$fixtureField=[pscustomobject]@{id=201;billid=-7;fieldname='test';fieldlabel=-201;fielddbtype='varchar(20)';fieldhtmltype='1';type=0;detailtable=$null}
function Read-GraphSource {
 param($Session,$Method,[string]$SourceName,[hashtable]$Scopes=@{})
 $rows=@()
 if($SourceName -in @('workflow_bill','B02_workflow_bill')){$rows=@($fixtureBill)}
 elseif($SourceName -in @('workflow_billfield','B02_workflow_billfield')){$rows=@($fixtureField)}
 elseif($SourceName -eq 'HtmlLabelInfo'){$rows=@($Scopes.label_ids|ForEach-Object {[pscustomobject]@{indexid=$_;languageid=7;labelname='test'}})}
 return [pscustomobject]@{rows=$rows;pages=@();scope_counts=[ordered]@{}}
}
function Read-GraphPhysicalMetadata {
 param($Session,$Method,[string[]]$Names)
 return [pscustomobject]@{physical_columns=@();physical_keys=@();physical_foreign_keys=@()}
}
$r=Read-ReferencePass
[ordered]@{closed=$r.reference_graph.closed;labels=@($r.tables.HtmlLabelInfo|ForEach-Object {$_.indexid}|Sort-Object)}|ConvertTo-Json -Compress
"""
            replacements=dict(SESSION=HOME/'readers/SqlSession.ps1',QUERIES=HOME/'readers/GraphQueries.ps1',READER=HOME/'readers/Read-B06.ps1',HOME=HOME,TEMP=temp,PYTHON=sys.executable,REGISTRY=HOME/'registry/B06.json')
            for key,value in replacements.items():code=code.replace('__'+key+'__',quote(value))
            result=subprocess.run([shutil.which('pwsh'),'-NoLogo','-NoProfile','-NonInteractive','-Command',code],capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout),dict(closed=True,labels=[-201,-101]))
if __name__=='__main__':unittest.main()
