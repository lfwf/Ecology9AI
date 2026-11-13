import json,shutil,subprocess,unittest
from pathlib import Path
HOME=Path(__file__).resolve().parents[1]
class ReaderPartitionTests(unittest.TestCase):
    def test_registered_node_partitions_preserve_duplicates_and_cap(self):
        shell=shutil.which('pwsh')
        self.assertIsNotNone(shell)
        helper=str(HOME/'readers/SqlSession.ps1').replace("'","''")
        code=r"""
$ErrorActionPreference='Stop'
. '__HELPER__'
function Invoke-OaQuery {
 param($Session,[string]$Sql,[hashtable]$Parameters,[int]$Cap)
 if($Sql -notlike '*@scope*' -or $Sql -like '*{scope_ids}*'){throw 'Unsafe partition template'}
 $rows=[Collections.Generic.List[object]]::new()
 foreach($id in ($Parameters.Values | Sort-Object)){
   1..3 | ForEach-Object {$rows.Add([pscustomobject]@{nodeid=$id;fieldid=$_})}
   if($id -eq 1){$rows.Add([pscustomobject]@{nodeid=1;fieldid=1})}
 }
 return ,$rows.ToArray()
}
$source=[pscustomobject]@{sql='SELECT nodeid,fieldid FROM dbo.workflow_nodeform WHERE nodeid IN ({scope_ids})';order_by='nodeid,fieldid';row_cap=70;partition_by=[pscustomobject]@{source='workflow_flownode';column='nodeid';batch_size=20;max_rows_per_partition=20000}}
$tables=@{workflow_flownode=@(1..23|ForEach-Object {[pscustomobject]@{nodeid=$_}})}
$result=Read-OaPartitions $null $source $tables
$capDetected=$false
$source.row_cap=69
try{Read-OaPartitions $null $source $tables | Out-Null}catch{$capDetected=$true}
[ordered]@{rows=$result.rows.Count;blocks=$result.pages.Count;duplicate_rows=@($result.rows|Where-Object {$_.nodeid -eq 1 -and $_.fieldid -eq 1}).Count;cap_detected=$capDetected} | ConvertTo-Json -Compress
""".replace('__HELPER__',helper)
        result=subprocess.run([shell,'-NoLogo','-NoProfile','-NonInteractive','-Command',code],capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        data=json.loads(result.stdout)
        self.assertEqual(data,dict(rows=70,blocks=2,duplicate_rows=2,cap_detected=True))
    def test_reference_scope_filters_types_and_parameterizes_integer_ids(self):
        helper=str(HOME/'readers/SqlSession.ps1').replace("'","''")
        code=r"""
$ErrorActionPreference='Stop'
. '__HELPER__'
function Invoke-OaQuery {
 param($Session,[string]$Sql,[hashtable]$Parameters,[int]$Cap)
 if($Sql -like '*{scope_ids}*' -or $Parameters.Values.Count -ne 2){throw 'Incorrect reference parameters'}
 return ,@($Parameters.Values | Sort-Object | ForEach-Object {[pscustomobject]@{id=$_}})
}
$source=[pscustomobject]@{sql='SELECT id FROM dbo.HrmDepartment WHERE id IN ({scope_ids})';order_by='id';row_cap=100;reference_scope=[pscustomobject]@{max_ids=1800;references=@([pscustomobject]@{source='rules';column='objid';filters=[pscustomobject]@{type=1}},[pscustomobject]@{source='people';column='departmentid'})}}
$tables=@{rules=@([pscustomobject]@{type=1;objid=7},[pscustomobject]@{type=3;objid=99});people=@([pscustomobject]@{departmentid='8'},[pscustomobject]@{departmentid=0},[pscustomobject]@{departmentid=$null},[pscustomobject]@{departmentid='1 OR 1=1'})}
$r=Read-OaReferencedScope $null $source $tables
$missing=$false
try {Read-OaReferencedScope $null $source @{rules=@()} | Out-Null}catch{$missing=$true}
[ordered]@{ids=@($r.rows|ForEach-Object {$_.id});row_count=$r.pages[0].row_count;missing_dependency_rejected=$missing}|ConvertTo-Json -Compress
""".replace('__HELPER__',helper)
        result=subprocess.run([shutil.which('pwsh'),'-NoLogo','-NoProfile','-NonInteractive','-Command',code],capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout),dict(ids=[7,8],row_count=2,missing_dependency_rejected=True))

if __name__=='__main__':unittest.main()
