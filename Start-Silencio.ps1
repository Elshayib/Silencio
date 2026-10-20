param(
    [ValidateSet('speech', 'speech-quality', 'speech-fast')]
    [string]$Profile
)
$ErrorActionPreference = 'Stop'
$packagedApplication = Join-Path $PSScriptRoot 'dist\Silencio\Silencio.exe'
$launchArguments = @()
if ($Profile) { $launchArguments += @('--profile', $Profile) }
if (Test-Path -LiteralPath $packagedApplication) {
    Start-Process -FilePath $packagedApplication -ArgumentList ($launchArguments + '--background') -WindowStyle Hidden
    exit 0
}
$pythonPath = (Get-Command python -CommandType Application | Select-Object -First 1).Source
$env:PYTHONPATH = Join-Path $PSScriptRoot 'src'
$pythonWindowless = Join-Path (Split-Path -Parent $pythonPath) 'pythonw.exe'
if (Test-Path -LiteralPath $pythonWindowless) { $pythonPath = $pythonWindowless }
Start-Process -FilePath $pythonPath -ArgumentList (@('-m', 'silencio.desktop') + $launchArguments) -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
