# Connection bootstrap only. Executes fixed SELECT statements, never business writes.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$Server,
    [ValidateRange(1, 65535)][int]$Port = 1433,
    [string]$Database = 'ecology',
    [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$UserName,
    [switch]$NetworkOnly,
    [switch]$SaveCredential,
    [switch]$UseSavedCredential,
    [switch]$TrustServerCertificate
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$localDirectory = Join-Path $PSScriptRoot '.local'
$credentialPath = Join-Path $localDirectory 'credential.clixml'
$profilePath = Join-Path $localDirectory 'connection.json'
$reportPath = Join-Path $localDirectory 'connection-test.json'
$effectiveTrustServerCertificate = $TrustServerCertificate.IsPresent

function Read-QueryRows {
    param([System.Data.SqlClient.SqlConnection]$Connection, [string]$Sql)
    $command = $Connection.CreateCommand()
    $command.CommandTimeout = 10
    $command.CommandText = $Sql
    $reader = $null
    try {
        $reader = $command.ExecuteReader()
        while ($reader.Read()) {
            $row = [ordered]@{}
            for ($column = 0; $column -lt $reader.FieldCount; $column++) {
                $row[$reader.GetName($column)] = if ($reader.IsDBNull($column)) { $null } else { $reader.GetValue($column) }
            }
            [pscustomobject]$row
        }
    }
    finally {
        if ($null -ne $reader) { $reader.Dispose() }
        $command.Dispose()
    }
}

function Test-Endpoint {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $pending = $client.ConnectAsync($Server, $Port)
        if (-not $pending.Wait(5000)) { throw 'TCP connection timed out after 5 seconds.' }
        $null = $pending.GetAwaiter().GetResult()
    }
    finally { $client.Dispose() }
}

$connection = $null
$credential = $null
$securePassword = $null
$report = [ordered]@{
    status = 'not_started'
    checked_at = [DateTimeOffset]::Now.ToString('o')
    server = $Server
    port = $Port
    database = $Database
    expected_login = $UserName
    tcp_reachable = $false
    authenticated = $false
    business_rows_read = 0
    read_only_enforcement = 'database permissions; no write test performed'
    permission_audit = 'partial; object and schema grants are not fully audited'
}

try {
    if ($env:OS -ne 'Windows_NT') { throw 'This bootstrap uses Windows DPAPI and must run on Windows.' }
    if ($NetworkOnly -and ($SaveCredential -or $UseSavedCredential)) { throw 'NetworkOnly cannot be combined with credential options.' }
    if ($SaveCredential -and $UseSavedCredential) { throw 'Choose SaveCredential or UseSavedCredential, not both.' }
    Test-Endpoint
    $report.tcp_reachable = $true
    if ($NetworkOnly) {
        $report.status = 'tcp_only'
        $report | ConvertTo-Json -Depth 8
        exit 0
    }

    if ($SaveCredential -and ((Test-Path -LiteralPath $credentialPath) -or (Test-Path -LiteralPath $profilePath))) {
        throw 'Saved connection files already exist. Use -UseSavedCredential to retest; no files were overwritten.'
    }
    if ($UseSavedCredential) {
        if (-not (Test-Path -LiteralPath $credentialPath) -or -not (Test-Path -LiteralPath $profilePath)) {
            throw 'No saved connection. Run with -SaveCredential in a local interactive PowerShell window first.'
        }
        $savedProfile = Get-Content -LiteralPath $profilePath -Raw | ConvertFrom-Json
        if ($savedProfile.server -ne $Server -or $savedProfile.port -ne $Port -or $savedProfile.database -ne $Database -or $savedProfile.user_name -ne $UserName) {
            throw 'The saved credential is bound to a different endpoint, database or login. It was not used.'
        }
        if (-not $PSBoundParameters.ContainsKey('TrustServerCertificate')) {
            if ($savedProfile.trust_server_certificate -isnot [bool]) {
                throw 'The saved certificate trust setting must be a JSON boolean.'
            }
            $effectiveTrustServerCertificate = $savedProfile.trust_server_certificate
        }
        $credential = Import-Clixml -LiteralPath $credentialPath
        if ($credential -isnot [System.Management.Automation.PSCredential] -or $credential.UserName -ne $UserName) {
            throw 'The saved credential is invalid or belongs to another login.'
        }
        $securePassword = $credential.Password
    }
    else {
        Write-Host ('SQL login: {0}; server: {1}:{2}; database: {3}' -f $UserName, $Server, $Port, $Database)
        $securePassword = Read-Host 'Enter the SQL password locally (hidden; do not paste it into chat)' -AsSecureString
        if ($securePassword.Length -eq 0) { throw 'Password was empty.' }
        $credential = New-Object System.Management.Automation.PSCredential($UserName, $securePassword)
    }
    if (-not $securePassword.IsReadOnly()) { $securePassword.MakeReadOnly() }

    $builder = New-Object System.Data.SqlClient.SqlConnectionStringBuilder
    $builder['Data Source'] = 'tcp:{0},{1}' -f $Server, $Port
    $builder['Initial Catalog'] = $Database
    $builder['Encrypt'] = $true
    $builder['TrustServerCertificate'] = $effectiveTrustServerCertificate
    $builder['Persist Security Info'] = $false
    $builder['Connect Timeout'] = 8
    $builder['Pooling'] = $false
    $builder['Application Name'] = 'OA-AI-ReadOnly-ConnectionProbe'
    $builder['ApplicationIntent'] = [System.Data.SqlClient.ApplicationIntent]::ReadOnly
    $connection = New-Object System.Data.SqlClient.SqlConnection($builder.ConnectionString)
    $connection.Credential = New-Object System.Data.SqlClient.SqlCredential($UserName, $securePassword)
    $report.tls_encryption_required = $true
    $report.tls_certificate_validation_required = -not $effectiveTrustServerCertificate
    $report.trust_server_certificate = $effectiveTrustServerCertificate
    $connection.Open()
    $report.authenticated = $true

    $identity = @(Read-QueryRows $connection @'
SELECT DB_NAME() AS database_name, ORIGINAL_LOGIN() AS original_login,
       USER_NAME() AS database_user, CONVERT(nvarchar(128), SERVERPROPERTY('ProductVersion')) AS server_version,
       SYSDATETIMEOFFSET() AS database_time,
       IS_SRVROLEMEMBER('sysadmin') AS is_sysadmin,
       IS_ROLEMEMBER('db_owner') AS is_db_owner,
       IS_ROLEMEMBER('db_datawriter') AS is_db_datawriter,
       IS_ROLEMEMBER('db_ddladmin') AS is_db_ddladmin;
'@)
    if ($identity.Count -ne 1 -or $identity[0].database_name -ne $Database -or $identity[0].original_login -ne $UserName) {
        throw 'Connected identity does not match the intended database and login.'
    }
    $report.identity = $identity[0]
    $report.database_permissions = @(Read-QueryRows $connection @'
SELECT permission_name FROM fn_my_permissions(NULL, 'DATABASE') ORDER BY permission_name;
'@)
    $report.high_privilege_roles_detected = @('is_sysadmin', 'is_db_owner', 'is_db_datawriter', 'is_db_ddladmin' | Where-Object { $identity[0].$_ -eq 1 })
    $report.database_write_permissions_detected = @($report.database_permissions | Where-Object {
        $_.permission_name -match '^(CONTROL|ALTER|CREATE|INSERT|UPDATE|DELETE|EXECUTE|IMPERSONATE|TAKE OWNERSHIP|ADMINISTER|BACKUP|CHECKPOINT)'
    } | ForEach-Object { $_.permission_name })
    $report.status = if ($report.high_privilege_roles_detected.Count -gt 0 -or $report.database_write_permissions_detected.Count -gt 0) {
        'connected_permission_review_required'
    } else { 'connected_metadata_checked' }

    if ($SaveCredential) {
        if ($report.status -ne 'connected_metadata_checked') {
            throw 'The connection worked, but broad privileges were detected. Credential was not saved; ask the DBA to review the report.'
        }
        $null = New-Item -ItemType Directory -Path $localDirectory -Force
        $profile = [ordered]@{ server = $Server; port = $Port; database = $Database; user_name = $UserName; encrypt = $true; trust_server_certificate = $effectiveTrustServerCertificate } | ConvertTo-Json
        $profileStream = [System.IO.File]::Open($profilePath, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
        try {
            $profileBytes = [System.Text.Encoding]::UTF8.GetBytes($profile)
            $profileStream.Write($profileBytes, 0, $profileBytes.Length)
        }
        finally { $profileStream.Dispose() }
        $credential | Export-Clixml -LiteralPath $credentialPath -NoClobber
        $report.credential_saved_with_windows_dpapi = $true
    }
}
catch {
    $report.status = 'failed'
    $report.error = $_.Exception.Message
    Write-Host 'Connection check failed. Credentials and connection settings will not be printed.'
}
finally {
    if ($null -ne $connection) { $connection.Dispose() }
    if ($null -ne $securePassword) { $securePassword.Dispose() }
}

$null = New-Item -ItemType Directory -Path $localDirectory -Force
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $reportPath -Encoding UTF8
$report | ConvertTo-Json -Depth 8
Write-Host ('Diagnostic report: {0}' -f $reportPath)
if ($report.status -eq 'failed' -or $report.status -eq 'connected_permission_review_required') { exit 1 }
exit 0
