# Internal native result-contract reader. Caller supplies registered sys queries only.
function Read-MetadataSource {
    param($Session,[string]$Sql,[hashtable]$ParameterValues,[int]$Cap)
    $remaining=[int][Math]::Floor($Session.Budget-$Session.Clock.Elapsed.TotalSeconds)
    if($remaining -le 0){throw 'Metadata read budget exceeded'}
    $command=$Session.Connection.CreateCommand();$reader=$null
    $command.CommandTimeout=[Math]::Min(10,$remaining);$command.CommandText=$Sql
    try{
        foreach($name in $ParameterValues.Keys){
            $type=if($ParameterValues[$name] -is [int]){[Data.SqlDbType]::Int}else{[Data.SqlDbType]::NVarChar}
            $parameter=if($type -eq [Data.SqlDbType]::Int){$command.Parameters.Add($name,$type)}else{$command.Parameters.Add($name,$type,128)}
            $parameter.Value=$ParameterValues[$name]
        }
        $reader=$command.ExecuteReader();$nativeSchema=$reader.GetSchemaTable()
        $contract=[Collections.Generic.List[object]]::new()
        foreach($c in $nativeSchema.Rows){
            $contract.Add([pscustomobject]@{column_name=[string]$c.ColumnName;ordinal=[int]$c.ColumnOrdinal;data_type=[string]$c.DataType.FullName;column_size=[int]$c.ColumnSize;allow_null=[bool]$c.AllowDBNull})
        }
        $rows=[Collections.Generic.List[object]]::new()
        while($reader.Read()){
            if($rows.Count -ge $Cap){throw 'Metadata row cap exceeded'}
            $row=[ordered]@{}
            for($i=0;$i -lt $reader.FieldCount;$i++){$row[$reader.GetName($i)]=if($reader.IsDBNull($i)){$null}else{$reader.GetValue($i)}}
            $rows.Add([pscustomobject]$row)
        }
        return [pscustomobject]@{rows=$rows.ToArray();contract=$contract.ToArray()}
    }finally{if($null -ne $reader){$reader.Dispose()};$command.Dispose()}
}
