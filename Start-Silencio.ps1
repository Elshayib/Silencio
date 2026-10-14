param(
    [ValidateSet('speech', 'speech-quality', 'speech-fast', 'aggressive', 'balanced')]
    [string]$Profile = 'speech'
)
$ErrorActionPreference = 'Stop'
$runtimePath = Join-Path $env:APPDATA 'Silencio\state.runtime.json'
if (Test-Path -LiteralPath $runtimePath) {
    try {
        $health = Get-Content -LiteralPath $runtimePath -Raw | ConvertFrom-Json
        $age = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - $health.updated_at
        if ($health.running -and $age -lt 3) {
            $existingSilencio = Get-CimInstance Win32_Process -Filter "ProcessId=$([int]$health.pid)"
            if ($existingSilencio -and $existingSilencio.CommandLine -match '\s-m silencio\s+--run\b') {
                Write-Output 'Silencio is already running. Use the tray icon or Ctrl+Alt+M.'
                exit 0
            }
        }
    } catch { }
}
$pythonPath = (Get-Command python -CommandType Application | Select-Object -First 1).Source
$env:PYTHONPATH = Join-Path $PSScriptRoot 'src'
$logDirectory = Join-Path $PSScriptRoot '.scratch'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$launchArgs = @('-u', '-m', 'silencio', '--run', '--on', '--profile', $Profile, '--backend', 'cpu', '--tray')
$liveProcess = Start-Process -FilePath $pythonPath -ArgumentList $launchArgs -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logDirectory 'live.log') -RedirectStandardError (Join-Path $logDirectory 'live-errors.log')
$startupDeadline = [DateTime]::UtcNow.AddSeconds(10)
while ([DateTime]::UtcNow -lt $startupDeadline) {
    Start-Sleep -Milliseconds 100
    $liveProcess.Refresh()
    if ($liveProcess.HasExited) {
        Get-Content -LiteralPath (Join-Path $logDirectory 'live-errors.log')
        Get-Content -LiteralPath (Join-Path $logDirectory 'live.log')
        exit 1
    }
    try {
        $health = Get-Content -LiteralPath $runtimePath -Raw | ConvertFrom-Json
        if ($health.pid -eq $liveProcess.Id -and $health.running -and $health.enabled) {
            Write-Output "Silencio is running ON ($Profile). Use the tray icon or Ctrl+Alt+M to toggle Music suppression."
            exit 0
        }
    } catch { }
}
Write-Output 'Silencio has not reported ready yet. Check .scratch/live-errors.log and python -m silencio --diagnose.'
exit 1
