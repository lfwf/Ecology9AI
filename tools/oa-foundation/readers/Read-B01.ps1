# Fixed B01 configuration reader. No business tables, arbitrary SQL or plaintext credentials.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$ConnectionDirectory,
    [Parameter(Mandatory=$true)][string]$OutputPath
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$connection = $null
$credential = $null
$stage = 'initialization'
$failureDetails = $null
$clock = [Diagnostics.Stopwatch]::StartNew()
$started = [DateTimeOffset]::UtcNow.ToString('o')
$registryPath = Join-Path (Split-Path $PSScriptRoot -Parent) 'registry/B01.json'
$method = Get-Content -LiteralPath $registryPath -Encoding UTF8 -Raw | ConvertFrom-Json
$tableNames = @('workflow_base', 'workflow_type', 'workflow_bill', 'workflow_formbase')

function Invoke-FixedSelect {
    param([string]$Text, [hashtable]$Parameters=@{}, [int]$Cap=501)
    $remaining = [int][Math]::Floor($method.limits.read_budget_seconds - $clock.Elapsed.TotalSeconds)
    if ($remaining -le 0) { throw 'Read budget exceeded.' }
    $command = $connection.CreateCommand()
    $command.CommandTimeout = [Math]::Min($method.limits.query_timeout_seconds, $remaining)
    $command.CommandText = $Text
    foreach ($name in $Parameters.Keys) {
        $parameter = $command.Parameters.Add($name, [Data.SqlDbType]::Int)
        $parameter.Value = $Parameters[$name]
    }
    $reader = $null
    try {
        $reader = $command.ExecuteReader()
        $rows = [Collections.Generic.List[object]]::new()
        while ($reader.Read()) {
            if ($rows.Count -ge $Cap) { throw 'Result exceeded query row cap.' }
            $row = [ordered]@{}
            for ($i=0; $i -lt $reader.FieldCount; $i++) {
                $row[$reader.GetName($i)] = if ($reader.IsDBNull($i)) { $null } else { $reader.GetValue($i) }
            }
            $rows.Add([pscustomobject]$row)
        }
        return ,$rows.ToArray()
    } finally {
        if ($null -ne $reader) { $reader.Dispose() }
        $command.Dispose()
    }
}

function Get-ContentHash {
    param($Value)
    $json = ConvertTo-Json -InputObject $Value -Depth 12 -Compress
    $hash = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($json)))).Replace('-','').ToLowerInvariant() }
    finally { $hash.Dispose() }
}

function Read-SelectedSchema {
    $metadata = Invoke-FixedSelect -Cap 500 -Text @'
SELECT o.name AS object_name, c.name AS column_name, t.name AS data_type,
       c.max_length, c.precision, c.scale, c.is_nullable,
       HAS_PERMS_BY_NAME(QUOTENAME(s.name)+'.'+QUOTENAME(o.name),'OBJECT','SELECT') AS can_select
FROM sys.objects o JOIN sys.schemas s ON s.schema_id=o.schema_id
JOIN sys.columns c ON c.object_id=o.object_id
JOIN sys.types t ON t.user_type_id=c.user_type_id
WHERE s.name='dbo' AND o.type='U'
AND o.name IN ('workflow_base','workflow_type','workflow_bill','workflow_formbase')
ORDER BY o.name,c.column_id;
'@
    $selected = [Collections.Generic.List[object]]::new()
    foreach ($table in $tableNames) {
        foreach ($field in $method.tables.$table.PSObject.Properties) {
            if ($field.Name -notmatch '^[A-Za-z][A-Za-z0-9_]*$') { throw 'Invalid registered column identifier.' }
            $column = @($metadata | Where-Object { $_.object_name -ceq $table -and $_.column_name -ceq $field.Name })
            if ($column.Count -ne 1 -or $column[0].data_type -cne $field.Value -or $column[0].can_select -ne 1) {
                $script:failureDetails = [ordered]@{code='schema_contract_mismatch';object=$table;column=$field.Name;expected_type=$field.Value;visible_matches=$column.Count}
                throw 'Registered column unavailable, changed type, or SELECT not permitted.'
            }
            $selected.Add($column[0])
        }
    }
    return ,$selected.ToArray()
}

function Read-ConfigurationTables {
    $tables = [ordered]@{}
    $coverage = [ordered]@{}
    foreach ($table in $tableNames) {
        # Identifiers come only from the reviewed, fixed registry; values remain SQL parameters.
        $fields = @($method.tables.$table.PSObject.Properties.Name)
        $projection = ($fields | ForEach-Object { '[' + $_ + ']' }) -join ','
        $items = [Collections.Generic.List[object]]::new()
        $last = $null
        $pages = 0
        $pageEvidence = [Collections.Generic.List[object]]::new()
        while ($true) {
            $parameters = @{ '@take'=[int]$method.limits.page_size }
            $where = ''
            if ($null -ne $last) { $where = ' WHERE id > @after'; $parameters['@after'] = $last }
            $page = Invoke-FixedSelect -Text ('SELECT TOP (@take) ' + $projection + ' FROM dbo.[' + $table + ']' + $where + ' ORDER BY id;') -Parameters $parameters -Cap $method.limits.page_size
            $pages++
            $pageEvidence.Add([pscustomobject]@{after_id=$last;take=$method.limits.page_size;row_count=$page.Count})
            foreach ($item in $page) {
                if ($items.Count -ge $method.limits.max_rows_per_table) { throw 'Configuration source exceeded row cap.' }
                if ($null -ne $last -and $item.id -le $last) { throw 'Non-unique or unordered source ID.' }
                $items.Add($item)
                $last = $item.id
            }
            if ($page.Count -lt $method.limits.page_size) { break }
        }
        $tables[$table] = $items.ToArray()
        $coverage[$table] = [ordered]@{complete=$true; row_count=$items.Count; pages=$pages;
            first_id=if($items.Count){$items[0].id}else{$null}; last_id=$last;page_parameters=$pageEvidence.ToArray()}
    }
    return [pscustomobject]@{tables=$tables; coverage=$coverage}
}

try {
    if (Test-Path -LiteralPath $OutputPath) { throw 'Output already exists.' }
    $profile = Get-Content -LiteralPath (Join-Path $ConnectionDirectory 'connection.json') -Encoding UTF8 -Raw | ConvertFrom-Json
    if ($profile.encrypt -ne $true -or $profile.trust_server_certificate -isnot [bool] -or
        [string]::IsNullOrWhiteSpace($profile.server) -or [string]::IsNullOrWhiteSpace($profile.database) -or
        [string]::IsNullOrWhiteSpace($profile.user_name) -or $profile.port -lt 1 -or $profile.port -gt 65535) {
        throw 'Invalid encrypted connection profile.'
    }
    $stage = 'credential'
    $credential = Import-Clixml -LiteralPath (Join-Path $ConnectionDirectory 'credential.clixml')
    if ($credential -isnot [Management.Automation.PSCredential] -or $credential.UserName -cne $profile.user_name) { throw 'Credential identity mismatch.' }
    if (-not $credential.Password.IsReadOnly()) { $credential.Password.MakeReadOnly() }
    $builder = [Data.SqlClient.SqlConnectionStringBuilder]::new()
    $builder['Data Source'] = 'tcp:{0},{1}' -f $profile.server,$profile.port
    $builder['Initial Catalog'] = $profile.database
    $builder['Encrypt'] = $true
    $builder['TrustServerCertificate'] = $profile.trust_server_certificate
    $builder['ApplicationIntent'] = 'ReadOnly'
    $builder['Application Name'] = 'OA-Foundation-B01'
    $builder['Persist Security Info'] = $false
    $builder['Pooling'] = $false
    $builder['Connect Timeout'] = 8
    $connection = [Data.SqlClient.SqlConnection]::new($builder.ConnectionString)
    $connection.Credential = [Data.SqlClient.SqlCredential]::new($credential.UserName,$credential.Password)
    $stage = 'connection'
    $connection.Open()
    $stage = 'identity'
    $identity = Invoke-FixedSelect -Cap 1 -Text @'
SET LOCK_TIMEOUT 3000;
SELECT DB_NAME() AS database_name, ORIGINAL_LOGIN() AS original_login, USER_NAME() AS database_user,
       CONVERT(nvarchar(128),SERVERPROPERTY('ServerName')) AS server_identity,
       CONVERT(nvarchar(128),SERVERPROPERTY('ProductVersion')) AS server_version,
       IS_SRVROLEMEMBER('sysadmin') AS is_sysadmin, IS_MEMBER('db_owner') AS is_db_owner,
       IS_MEMBER('db_datawriter') AS is_db_datawriter, IS_MEMBER('db_ddladmin') AS is_db_ddladmin;
'@
    if ($identity.Count -ne 1 -or $identity[0].database_name -cne $profile.database -or
        $identity[0].original_login -cne $profile.user_name -or $identity[0].is_sysadmin -ne 0 -or
        $identity[0].is_db_owner -ne 0 -or $identity[0].is_db_datawriter -ne 0 -or $identity[0].is_db_ddladmin -ne 0) {
        throw 'Unexpected database identity or broad privilege role.'
    }
    $stage = 'schema'
    $schema = Read-SelectedSchema
    $stage = 'first_pass'
    $first = Read-ConfigurationTables
    $stage = 'second_pass'
    $second = Read-ConfigurationTables
    $stage = 'consistency'
    if ((Get-ContentHash $schema) -cne (Get-ContentHash (Read-SelectedSchema))) { throw 'Schema changed during capture.' }
    foreach ($table in $tableNames) {
        $hashFirst = Get-ContentHash $first.tables[$table]
        $hashSecond = Get-ContentHash $second.tables[$table]
        if ($hashFirst -cne $hashSecond) { throw 'Configuration changed during capture.' }
        $first.coverage[$table]['hash_first'] = $hashFirst
        $first.coverage[$table]['hash_second'] = $hashSecond
        $first.coverage[$table]['second_pass_pages'] = $second.coverage[$table].pages
    }
    if ($first.tables['workflow_base'].Count -eq 0) { throw 'Empty workflow directory rejected.' }
    $stage = 'save'
    $result = [ordered]@{
        format_version=1; category='B01'; method_version=$method.method_version;
        started_at=$started; ended_at=[DateTimeOffset]::UtcNow.ToString('o');
        source_identity=[ordered]@{server=$profile.server; port=$profile.port; database=$identity[0].database_name;
            server_identity=$identity[0].server_identity; server_version=$identity[0].server_version;
            login=$identity[0].original_login; database_user=$identity[0].database_user};
        transport=[ordered]@{encrypt=$true;trust_server_certificate=$profile.trust_server_certificate};
        privilege_checks=$identity[0]; permission_audit='limited role and selected source SELECT checks; no write test or full account audit';
        scope=$method.scope; consistency=$method.consistency; business_rows_read=0;
        implementation_hashes=[ordered]@{reader=(Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash; registry=(Get-FileHash -LiteralPath $registryPath -Algorithm SHA256).Hash};
        schema=$schema; tables=$first.tables; checks=$first.coverage
    }
    $json = ConvertTo-Json -InputObject $result -Depth 15
    $stream = [IO.File]::Open($OutputPath,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
    try { $bytes=[Text.UTF8Encoding]::new($false).GetBytes($json); $stream.Write($bytes,0,$bytes.Length) }
    finally { $stream.Dispose() }
    Write-Output '{"status":"captured","category":"B01","business_rows_read":0}'
} catch {
    # No exception text or connection settings: driver errors may contain sensitive details.
    $failure = [ordered]@{status='failed';stage=$stage;business_rows_read=0;details=$failureDetails}
    $driverError = $_.Exception.GetBaseException()
    if ($driverError -is [Data.SqlClient.SqlException]) { $failure['sql_error_number'] = $driverError.Number }
    Write-Output (ConvertTo-Json -InputObject $failure -Depth 5 -Compress)
    exit 1
} finally {
    if ($null -ne $connection) { $connection.Dispose() }
    if ($null -ne $credential -and $credential -is [Management.Automation.PSCredential]) { $credential.Password.Dispose() }
}
