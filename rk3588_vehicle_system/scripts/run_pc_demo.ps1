param(
    [int]$MaxFrames = 610,
    [switch]$NoDisplay
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$executable = Join-Path $projectRoot 'build\windows-x64\bin\vehicle_demo.exe'
if (-not (Test-Path -LiteralPath $executable)) {
    throw 'vehicle_demo.exe not found. Run scripts/build_windows.ps1 first.'
}

$arguments = @('--config', (Join-Path $projectRoot 'config\config.yaml'), '--max-frames', $MaxFrames)
if ($NoDisplay) {
    $arguments += '--no-display'
}
& $executable @arguments
exit $LASTEXITCODE

