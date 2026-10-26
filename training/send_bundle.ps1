[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ValidationReport,
    [string]$Runpodctl = "$HOME\Downloads\runpodctl.exe",
    [switch]$CheckOnly,
    [switch]$NewTransfer
)
$ErrorActionPreference = 'Stop'
$report = Get-Content -LiteralPath $ValidationReport -Raw | ConvertFrom-Json
if ($report.name -cnotmatch '^[a-z0-9][a-z0-9_]{0,63}$') { throw 'Invalid job name' }
if ($report.sha256 -cnotmatch '^[0-9a-f]{64}$') { throw 'Invalid SHA256' }
$bundle = (Resolve-Path -LiteralPath $report.bundle).Path
if ((Split-Path -Leaf $bundle) -cne "moss_$($report.name)_run.tar.gz") { throw 'Unexpected bundle filename' }
if ((Get-FileHash -LiteralPath $bundle -Algorithm SHA256).Hash.ToLowerInvariant() -ne $report.sha256) {
    throw 'Bundle checksum mismatch'
}
if ((Get-Item -LiteralPath $bundle).Length -ne $report.bytes) { throw 'Bundle size mismatch' }
$directory = Split-Path -Parent $bundle
$stateFile = Join-Path $directory "$($report.name)_send_state.json"
if ($CheckOnly) {
    [pscustomobject]@{state='ready';name=$report.name;bundle=$bundle;images=$report.images;steps=$report.steps} | ConvertTo-Json
    return
}
if (!(Test-Path -LiteralPath $Runpodctl -PathType Leaf)) { throw 'runpodctl.exe not found' }
$state = $null
if (Test-Path -LiteralPath $stateFile) {
    $prior = Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
    $active = Get-Process -Id $prior.pid -ErrorAction SilentlyContinue
    if ($active -and $active.ProcessName -eq 'runpodctl' -and
        $active.StartTime.ToUniversalTime().Ticks -eq [long]$prior.processStartTicks) {
        if ($prior.bundleSha256 -ne $report.sha256) { throw 'A different bundle is already being sent' }
        $state = $prior
    } elseif (!$NewTransfer) {
        throw "Previous sender exited. Inspect $($prior.stdout) and $($prior.stderr); use -NewTransfer only for an authorized resend."
    }
}
if (!$state) {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
    $stdout = Join-Path $directory "send-$($report.name)-$stamp.out.log"
    $stderr = Join-Path $directory "send-$($report.name)-$stamp.err.log"
    $process = Start-Process -FilePath $Runpodctl -ArgumentList @('send', ('"' + $bundle + '"')) `
        -WorkingDirectory $directory -WindowStyle Hidden -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr -PassThru
    $state = [pscustomobject]@{name=$report.name;pid=$process.Id;
        processStartTicks=$process.StartTime.ToUniversalTime().Ticks;
        bundleSha256=$report.sha256;stdout=$stdout;stderr=$stderr}
    $state | ConvertTo-Json | Set-Content -LiteralPath $stateFile -Encoding utf8
}
$code = $null
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    $text = ''
    foreach ($log in @($state.stdout, $state.stderr)) {
        if (Test-Path -LiteralPath $log) { $text += Get-Content -LiteralPath $log -Raw }
    }
    $match = [regex]::Match($text, '(?m)^\s*(?:code is:\s*)?(\d{4}-[a-z]+-[a-z]+-[a-z]+-\d+)\s*$')
    if ($match.Success) { $code = $match.Groups[1].Value; break }
    if (!(Get-Process -Id $state.pid -ErrorAction SilentlyContinue)) { break }
    Start-Sleep -Milliseconds 500
}
if (!$code) { throw "Receive code unavailable; inspect $($state.stdout) and $($state.stderr). Sender PID=$($state.pid)." }
$active = Get-Process -Id $state.pid -ErrorAction SilentlyContinue
if (!$active -or $active.StartTime.ToUniversalTime().Ticks -ne [long]$state.processStartTicks) {
    throw "Sender already exited; do not reuse its code. Inspect $($state.stdout) and $($state.stderr)."
}
if ($text -match '100%') { throw 'Transfer already reached 100%; do not reuse this receive code.' }
$name = $report.name
$command = "bash /workspace/MossImage/train.sh receive $name --code $code --sha256 $($report.sha256)"
[pscustomobject]@{state='waiting_for_receiver';name=$name;pid=$state.pid;code=$code;
    images=$report.images;steps=$report.steps;command=$command;stdout=$state.stdout;stderr=$state.stderr} | ConvertTo-Json
