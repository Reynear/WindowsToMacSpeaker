# ffmpeg_progress_to_csv.ps1
# Converts FFmpeg -progress log to a CSV with one row per interval

param(
    [string]$InputFile = "audio_stream_progress.txt",
    [string]$OutputFile = "audio_stream_metrics.csv"
)

# Read all lines, group by 'progress=' (each group is one interval)
$lines = Get-Content $InputFile | Where-Object {$_ -match "="}
$groups = @()
$group = @()
foreach ($line in $lines) {
    if ($line -like "progress=*") {
        $group += $line
        $groups += ,@($group)
        $group = @()
    } else {
        $group += $line
    }
}

# Collect all unique keys for CSV header
$allKeys = $groups | ForEach-Object {
    $_ | ForEach-Object {
        if ($_ -match "^(.*?)=") { $matches[1] }
    }
} | Sort-Object -Unique

# Write CSV header
$header = $allKeys -join ","
Set-Content $OutputFile $header

# Write each group as a CSV row
foreach ($g in $groups) {
    $dict = @{}
    foreach ($line in $g) {
        if ($line -match "^(.*?)=(.*)$") {
            $dict[$matches[1]] = $matches[2]
        }
    }
    $row = $allKeys | ForEach-Object { $dict[$_] }
    Add-Content $OutputFile ($row -join ",")
}

Write-Host "CSV created: $OutputFile"