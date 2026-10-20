param(
    [Parameter(Mandatory=$true)][switch]$LicensedDriver,
    [string]$Python = 'python',
    [string]$Iscc = 'ISCC.exe'
)
$ErrorActionPreference = 'Stop'
$repoDirectory = Split-Path -Parent $PSScriptRoot
Push-Location $repoDirectory
try {
    & $Python scripts/prepare_release.py --licensed-driver
    if ($LASTEXITCODE -ne 0) { throw 'Release preparation failed' }
    & $Python -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
    & $Python -m mypy src/silencio
    if ($LASTEXITCODE -ne 0) { throw 'Type checks failed' }
    & $Python -m PyInstaller --noconfirm packaging/Silencio.spec
    if ($LASTEXITCODE -ne 0) { throw 'Executable build failed' }
    $reportPath = Join-Path $repoDirectory 'build/frozen-self-test.json'
    $testProcess = Start-Process -FilePath 'dist/Silencio/Silencio.exe' -ArgumentList @('--self-test', ('"' + $reportPath + '"')) -WindowStyle Hidden -PassThru -Wait
    if ($testProcess.ExitCode -ne 0) { throw 'Packaged application self-test failed' }
    & $Iscc packaging/Silencio.iss
    if ($LASTEXITCODE -ne 0) { throw 'Installer compilation failed' }
    Get-ChildItem dist -Filter 'Silencio-Setup-*.exe' | ForEach-Object {
        $hash = Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256
        ($hash.Hash.ToLower() + '  ' + $_.Name) | Set-Content -LiteralPath ($_.FullName + '.sha256')
        Write-Output $_.FullName
    }
} finally {
    Pop-Location
}
