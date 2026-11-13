# Fixed metadata inventory for the authorized OA database. No business rows.
[CmdletBinding()]
param([int]$WorkflowId=0)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$localDirectory = Join-Path $PSScriptRoot '.local'
$profile = Get-Content -LiteralPath (Join-Path $localDirectory 'connection.json') -Raw | ConvertFrom-Json
if ([string]::IsNullOrWhiteSpace($profile.server) -or [string]::IsNullOrWhiteSpace($profile.database) -or [string]::IsNullOrWhiteSpace($profile.user_name) -or $profile.port -lt 1 -or $profile.port -gt 65535) {
    throw 'Invalid local connection profile.'
}
if ($profile.trust_server_certificate -isnot [bool]) { throw 'Invalid saved certificate trust setting.' }
$credential = Import-Clixml -LiteralPath (Join-Path $localDirectory 'credential.clixml')
if ($credential -isnot [System.Management.Automation.PSCredential] -or $credential.UserName -ne $profile.user_name) {
    throw 'The saved credential does not match the intended login.'
}
if (-not $credential.Password.IsReadOnly()) { $credential.Password.MakeReadOnly() }
$builder = New-Object System.Data.SqlClient.SqlConnectionStringBuilder
$builder['Data Source'] = 'tcp:{0},{1}' -f $profile.server, $profile.port
$builder['Initial Catalog'] = $profile.database
$builder['Encrypt'] = $true
$builder['TrustServerCertificate'] = $profile.trust_server_certificate
$builder['ApplicationIntent'] = [System.Data.SqlClient.ApplicationIntent]::ReadOnly
$builder['Application Name'] = 'OA-AI-ReadOnly-SchemaInventory'
$builder['Persist Security Info'] = $false
$builder['Pooling'] = $false
$builder['Connect Timeout'] = 8
$connection = New-Object System.Data.SqlClient.SqlConnection($builder.ConnectionString)
$connection.Credential = New-Object System.Data.SqlClient.SqlCredential($credential.UserName, $credential.Password)
$command = $null
$reader = $null
$targets = @(
    'workflow_base', 'workflow_bill', 'workflow_billfield', 'workflow_billdetailtable',
    'workflow_flownode', 'workflow_nodebase', 'workflow_nodelink', 'workflow_nodegroup',
    'workflow_groupdetail', 'workflow_currentoperator', 'workflow_requestbase', 'workflow_requestlog',
    'workflowactionset', 'actionsetting', 'rule_base', 'rule_maplist', 'rule_expressionbase',
    'rule_expressions', 'workflow_nodeform', 'workflow_nodehtmllayout', 'workflow_formdetail',
    'workflow_billdetailtable'
)
try {
    $connection.Open()
    $command = $connection.CreateCommand()
    $command.CommandTimeout = 10
    $placeholders = for ($i = 0; $i -lt $targets.Count; $i++) {
        $name = '@object' + $i
        $parameter = $command.Parameters.Add($name, [System.Data.SqlDbType]::NVarChar, 128)
        $parameter.Value = $targets[$i]
        $name
    }
    # Only trusted, generated parameter names are inserted; values stay parameters.
    $filter = $placeholders -join ','
    $command.CommandText = @"
SELECT s.name AS schema_name, o.name AS object_name, o.type_desc,
       c.column_id, c.name AS column_name, t.name AS data_type,
       c.max_length, c.precision, c.scale, c.is_nullable, c.is_identity,
       HAS_PERMS_BY_NAME(QUOTENAME(s.name)+'.'+QUOTENAME(o.name), 'OBJECT', 'SELECT') AS can_select,
       HAS_PERMS_BY_NAME(QUOTENAME(s.name)+'.'+QUOTENAME(o.name), 'OBJECT', 'INSERT') AS can_insert,
       HAS_PERMS_BY_NAME(QUOTENAME(s.name)+'.'+QUOTENAME(o.name), 'OBJECT', 'UPDATE') AS can_update,
       HAS_PERMS_BY_NAME(QUOTENAME(s.name)+'.'+QUOTENAME(o.name), 'OBJECT', 'DELETE') AS can_delete,
       HAS_PERMS_BY_NAME(QUOTENAME(s.name)+'.'+QUOTENAME(o.name), 'OBJECT', 'ALTER') AS can_alter
FROM sys.objects AS o
JOIN sys.schemas AS s ON s.schema_id = o.schema_id
JOIN sys.columns AS c ON c.object_id = o.object_id
JOIN sys.types AS t ON t.user_type_id = c.user_type_id
WHERE o.type IN ('U','V') AND o.name IN ($filter)
ORDER BY s.name, o.name, c.column_id;
"@
    $reader = $command.ExecuteReader()
    $rows = [System.Collections.Generic.List[object]]::new()
    while ($reader.Read()) {
        if ($rows.Count -ge 4000) { throw 'Metadata result exceeded the 4000-column cap; inventory was not saved.' }
        $row = [ordered]@{}
        for ($i = 0; $i -lt $reader.FieldCount; $i++) {
            $row[$reader.GetName($i)] = if ($reader.IsDBNull($i)) { $null } else { $reader.GetValue($i) }
        }
        $rows.Add([pscustomobject]$row)
    }
    $snapshot = [ordered]@{
        collected_at = [DateTimeOffset]::Now.ToString('o')
        database = $profile.database
        scope = 'fixed OA workflow metadata targets'
        business_rows_read = 0
        metadata_column_count = $rows.Count
        metadata_visibility = 'only objects visible to current login; absent is not proof of nonexistence'
        permission_audit = 'SELECT and listed write permissions on selected tables/views only; not full account audit'
        requested_objects = $targets
        columns = $rows.ToArray()
    }
    if ($WorkflowId -gt 0) {
        $reader.Dispose()
        $reader = $null
        $command.Parameters.Clear()
        $command.CommandText = @'
SELECT TOP (1) w.id AS workflow_id, w.workflowname, w.formid, w.isbill,
       w.version AS version_raw, w.activeVersionID AS active_version_id_raw, w.isvalid AS isvalid_raw,
       (SELECT COUNT(*) FROM dbo.workflow_flownode AS n WHERE n.workflowid = w.id) AS node_count,
       (SELECT COUNT(*) FROM dbo.workflow_nodelink AS l WHERE l.workflowid = w.id) AS link_count,
       (SELECT TOP (1) b.tablename FROM dbo.workflow_bill AS b WHERE b.id = w.formid) AS bill_table_name,
       (SELECT TOP (1) b.tablename FROM dbo.workflow_bill AS b WHERE b.id = ABS(w.formid)) AS bill_table_name_from_absolute_id
FROM dbo.workflow_base AS w WHERE w.id = @workflow;
'@
        $parameter = $command.Parameters.Add('@workflow', [System.Data.SqlDbType]::Int)
        $parameter.Value = $WorkflowId
        $reader = $command.ExecuteReader()
        $definitions = [System.Collections.Generic.List[object]]::new()
        while ($reader.Read()) {
            $definition = [ordered]@{}
            for ($i = 0; $i -lt $reader.FieldCount; $i++) {
                $definition[$reader.GetName($i)] = if ($reader.IsDBNull($i)) { $null } else { $reader.GetValue($i) }
            }
            $definitions.Add([pscustomobject]$definition)
        }
        $snapshot.workflow_definition = $definitions.ToArray()
        $snapshot.configuration_rows_read = $definitions.Count
    }
    $file = Join-Path $localDirectory ('schema-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff') + '.json')
    $snapshot | ConvertTo-Json -Depth 7 | Set-Content -LiteralPath $file -Encoding UTF8
    $objects = @($rows | Group-Object schema_name, object_name)
    Write-Output ('Inventory saved: ' + $file)
    Write-Output ('Visible objects: {0}; columns: {1}; business rows: 0' -f $objects.Count, $rows.Count)
    foreach ($group in $objects) {
        $item = $group.Group[0]
        Write-Output ('{0}.{1}: {2} columns; SELECT={3}; INSERT={4}; UPDATE={5}; DELETE={6}; ALTER={7}' -f $item.schema_name, $item.object_name, $group.Count, $item.can_select, $item.can_insert, $item.can_update, $item.can_delete, $item.can_alter)
    }
    if ($WorkflowId -gt 0) { $snapshot.workflow_definition | ConvertTo-Json -Depth 4 }
}
finally {
    if ($null -ne $reader) { $reader.Dispose() }
    if ($null -ne $command) { $command.Dispose() }
    $connection.Dispose()
    $credential.Password.Dispose()
}
