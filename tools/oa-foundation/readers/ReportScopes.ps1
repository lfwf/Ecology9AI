# Scope selection from bounded report identity directories; never execute stored SQL.
function Select-OaReportScope {
    param($Rows,$Workflows,[string]$ListColumn)
    $wfids=[Collections.Generic.HashSet[int]]::new()
    $forms=[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    foreach($w in $Workflows){[void]$wfids.Add([int]$w.id);[void]$forms.Add(([string]$w.isbill+'/'+[string]$w.formid))}
    $ids=[Collections.Generic.HashSet[int]]::new()
    foreach($row in $Rows){
        $match=$forms.Contains(([string]$row.isbill+'/'+[string]$row.formid))
        $list=[string]$row.$ListColumn
        if($list -match '^\s*[0-9]+\s*(?:,\s*[0-9]+\s*)*$'){
            $numbers=[Collections.Generic.List[int]]::new();$valid=$true
            foreach($item in $list.Split(',')){
                $number=0
                if(-not [int]::TryParse($item.Trim(),[ref]$number)){$valid=$false;break}
                $numbers.Add($number)
            }
            if($valid){foreach($number in $numbers){if($wfids.Contains($number)){$match=$true}}}
        }
        if($match){[void]$ids.Add([int]$row.id)}
    }
    return ,@($ids|Sort-Object)
}
