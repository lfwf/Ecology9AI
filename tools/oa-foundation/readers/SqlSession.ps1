# Internal helpers: registered fixed-query readers only; no command-line SQL endpoint.
Set-StrictMode -Version Latest
function Open-OaSession {
    param([string]$ConnectionDirectory,[int]$BudgetSeconds=180)
    $credential=$null; $connection=$null
    try {
        $profile=Get-Content -LiteralPath (Join-Path $ConnectionDirectory 'connection.json') -Encoding UTF8 -Raw | ConvertFrom-Json
        if($profile.encrypt -ne $true -or $profile.trust_server_certificate -isnot [bool] -or
           [string]::IsNullOrWhiteSpace($profile.server) -or [string]::IsNullOrWhiteSpace($profile.database) -or
           [string]::IsNullOrWhiteSpace($profile.user_name) -or $profile.port -lt 1 -or $profile.port -gt 65535){throw 'Invalid encrypted profile'}
        $credential=Import-Clixml -LiteralPath (Join-Path $ConnectionDirectory 'credential.clixml')
        if($credential -isnot [Management.Automation.PSCredential] -or $credential.UserName -cne $profile.user_name){throw 'Credential identity mismatch'}
        if(-not $credential.Password.IsReadOnly()){$credential.Password.MakeReadOnly()}
        $builder=[Data.SqlClient.SqlConnectionStringBuilder]::new()
        $builder['Data Source']='tcp:{0},{1}' -f $profile.server,$profile.port
        $builder['Initial Catalog']=$profile.database; $builder['Encrypt']=$true
        $builder['TrustServerCertificate']=$profile.trust_server_certificate
        $builder['ApplicationIntent']='ReadOnly'; $builder['Application Name']='OAAI-Configuration'
        $builder['Persist Security Info']=$false; $builder['Pooling']=$false; $builder['Connect Timeout']=8
        $connection=[Data.SqlClient.SqlConnection]::new($builder.ConnectionString)
        $connection.Credential=[Data.SqlClient.SqlCredential]::new($credential.UserName,$credential.Password)
        $session=[pscustomobject]@{Connection=$connection;Credential=$credential;Profile=$profile;Clock=[Diagnostics.Stopwatch]::StartNew();Budget=$BudgetSeconds;Identity=$null}
        $connection.Open()
        $identitySql=@'
SET LOCK_TIMEOUT 3000;
SELECT DB_NAME() AS database_name,ORIGINAL_LOGIN() AS original_login,USER_NAME() AS database_user,
CONVERT(nvarchar(128),SERVERPROPERTY('ServerName')) AS server_identity,
CONVERT(nvarchar(128),SERVERPROPERTY('ProductVersion')) AS server_version,
IS_SRVROLEMEMBER('sysadmin') AS is_sysadmin,IS_MEMBER('db_owner') AS is_db_owner,
IS_MEMBER('db_datawriter') AS is_db_datawriter,IS_MEMBER('db_ddladmin') AS is_db_ddladmin;
'@
        $identity=Invoke-OaQuery $session $identitySql @{} 1
        if($identity.Count -ne 1 -or $identity[0].database_name -cne $profile.database -or
           $identity[0].original_login -cne $profile.user_name -or $identity[0].is_sysadmin -ne 0 -or
           $identity[0].is_db_owner -ne 0 -or $identity[0].is_db_datawriter -ne 0 -or $identity[0].is_db_ddladmin -ne 0){throw 'Unexpected identity or broad role'}
        $session.Identity=$identity[0]
        return $session
    } catch {
        if($null -ne $connection){$connection.Dispose()}
        if($null -ne $credential -and $credential -is [Management.Automation.PSCredential]){$credential.Password.Dispose()}
        throw
    }
}
function Close-OaSession {
    param($Session)
    if($null -ne $Session){$Session.Connection.Dispose();$Session.Credential.Password.Dispose()}
}
function Invoke-OaQuery {
    param($Session,[string]$Sql,[hashtable]$Parameters=@{},[int]$Cap=1000)
    $remaining=[int][Math]::Floor($Session.Budget-$Session.Clock.Elapsed.TotalSeconds)
    if($remaining -le 0){throw 'Read budget exceeded'}
    $command=$Session.Connection.CreateCommand();$command.CommandTimeout=[Math]::Min(10,$remaining);$command.CommandText=$Sql
    $reader=$null
    try {
        foreach($name in $Parameters.Keys){
            if($Parameters[$name] -is [int]){$parameter=$command.Parameters.Add($name,[Data.SqlDbType]::Int)}
            else{$parameter=$command.Parameters.Add($name,[Data.SqlDbType]::NVarChar,4000)}
            $parameter.Value=$Parameters[$name]
        }
        $reader=$command.ExecuteReader();$rows=[Collections.Generic.List[object]]::new()
        while($reader.Read()){
            if($rows.Count -ge $Cap){throw 'Query row cap exceeded'}
            $row=[ordered]@{}
            for($i=0;$i -lt $reader.FieldCount;$i++){$row[$reader.GetName($i)]=if($reader.IsDBNull($i)){$null}else{$reader.GetValue($i)}}
            $rows.Add([pscustomobject]$row)
        }
        return ,$rows.ToArray()
    } finally {if($null -ne $reader){$reader.Dispose()};$command.Dispose()}
}
function Read-OaPages {
    param($Session,[string]$Sql,[string]$Order,[int]$Cap=50000,[hashtable]$Parameters=@{})
    $rows=[Collections.Generic.List[object]]::new();$pages=[Collections.Generic.List[object]]::new();$offset=0
    while($true){
        $args=@{};foreach($key in $Parameters.Keys){$args[$key]=$Parameters[$key]}
        $args['@offset']=[int]$offset;$args['@take']=500
        $page=Invoke-OaQuery $Session ($Sql+' ORDER BY '+$Order+' OFFSET @offset ROWS FETCH NEXT @take ROWS ONLY;') $args 500
        $pages.Add([pscustomobject]@{offset=$offset;take=500;row_count=$page.Count})
        foreach($row in $page){if($rows.Count -ge $Cap){throw 'Source row cap exceeded'};$rows.Add($row)}
        if($page.Count -lt 500){break};$offset+=500
    }
    return [pscustomobject]@{rows=$rows.ToArray();pages=$pages.ToArray();complete=$true}
}
function Get-OaHash {
    param($Value)
    $json=ConvertTo-Json -InputObject $Value -Depth 25 -Compress
    $hash=[Security.Cryptography.SHA256]::Create()
    try{return ([BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($json)))).Replace('-','').ToLowerInvariant()}
    finally{$hash.Dispose()}
}
function Write-OaCapture {
    param([string]$Path,$Value)
    $bytes=[Text.UTF8Encoding]::new($false).GetBytes((ConvertTo-Json -InputObject $Value -Depth 25))
    $stream=[IO.File]::Open($Path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
    try{$stream.Write($bytes,0,$bytes.Length)}finally{$stream.Dispose()}
}

function Read-OaPartitions {
    param($Session,$Source,[System.Collections.IDictionary]$Tables)
    if(-not $Source.sql.Contains('{scope_ids}')){throw 'Partition SQL template is missing scope placeholder'}
    $part=$Source.partition_by
    if($part.batch_size -lt 1 -or $part.batch_size -gt 100){throw 'Partition size invalid'}
    $ids=@($Tables[$part.source] | ForEach-Object {[int]($_.($part.column))} | Sort-Object -Unique)
    $rows=[Collections.Generic.List[object]]::new();$pages=[Collections.Generic.List[object]]::new()
    for($offset=0;$offset -lt $ids.Count;$offset+=$part.batch_size){
        $stop=[Math]::Min($offset+$part.batch_size,$ids.Count)
        $parameters=@{};$placeholders=[Collections.Generic.List[string]]::new();$scopeIds=[Collections.Generic.List[int]]::new()
        for($i=$offset;$i -lt $stop;$i++){
            $name='@scope'+($i-$offset);$parameters[$name]=[int]$ids[$i];$placeholders.Add($name);$scopeIds.Add([int]$ids[$i])
        }
        $sql=$Source.sql.Replace('{scope_ids}',($placeholders -join ','))+' ORDER BY '+$Source.order_by+';'
        $block=Invoke-OaQuery $Session $sql $parameters $part.max_rows_per_partition
        foreach($row in $block){if($rows.Count -ge $Source.row_cap){throw 'Source row cap exceeded'};$rows.Add($row)}
        $pages.Add([pscustomobject]@{scope_ids=$scopeIds.ToArray();row_count=$block.Count;row_cap=$part.max_rows_per_partition})
    }
    return [pscustomobject]@{rows=$rows.ToArray();pages=$pages.ToArray();complete=$true;scope_id_count=$ids.Count}
}

function Read-OaReferencedScope {
    param($Session,$Source,[System.Collections.IDictionary]$Tables)
    if(-not $Source.sql.Contains('{scope_ids}')){throw 'Reference SQL template missing'}
    $scope=$Source.reference_scope
    if($scope.max_ids -lt 1 -or $scope.max_ids -gt 1800){throw 'Reference parameter cap invalid'}
    $ids=[Collections.Generic.HashSet[int]]::new()
    foreach($reference in $scope.references){
        if(-not $Tables.Contains($reference.source)){throw 'Reference dependency missing'}
        foreach($row in $Tables[$reference.source]){
            $matches=$true
            if($reference.PSObject.Properties.Name -contains 'filters'){
                foreach($filter in $reference.filters.PSObject.Properties){
                    if($row.PSObject.Properties.Name -notcontains $filter.Name){throw 'Reference filter column missing'}
                    if([string]$row.($filter.Name) -cne [string]$filter.Value){$matches=$false;break}
                }
            }
            if(-not $matches){continue}
            if($row.PSObject.Properties.Name -notcontains $reference.column){throw 'Reference id column missing'}
            $value=0
            if([int]::TryParse([string]$row.($reference.column),[ref]$value) -and $value -gt 0){[void]$ids.Add($value)}
        }
    }
    if($ids.Count -gt $scope.max_ids){throw 'Reference parameter cap exceeded'}
    if($ids.Count -eq 0){return [pscustomobject]@{rows=@();pages=@([pscustomobject]@{scope_ids=@();row_count=0});complete=$true}}
    $parameters=@{};$placeholders=[Collections.Generic.List[string]]::new();$i=0
    foreach($id in ($ids | Sort-Object)){
        $name='@scope'+$i;$parameters[$name]=[int]$id;$placeholders.Add($name);$i++
    }
    $sql=$Source.sql.Replace('{scope_ids}',($placeholders -join ','))+' ORDER BY '+$Source.order_by+';'
    $rows=Invoke-OaQuery $Session $sql $parameters $Source.row_cap
    return [pscustomobject]@{rows=$rows;pages=@([pscustomobject]@{scope_ids=@($ids|Sort-Object);row_count=$rows.Count});complete=$true}
}
