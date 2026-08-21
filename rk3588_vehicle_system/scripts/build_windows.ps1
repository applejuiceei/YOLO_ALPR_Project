param(
    [ValidateSet('Release', 'Debug')]
    [string]$Configuration = 'Release'
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$buildDir = Join-Path $projectRoot 'build\windows-x64'
$vswhere = 'C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe'

if (-not (Test-Path -LiteralPath $vswhere)) {
    throw 'Visual Studio Build Tools vswhere.exe was not found.'
}

$installPath = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $installPath) {
    throw 'Visual Studio C++ Build Tools were not found.'
}
$vcvars = Join-Path $installPath 'VC\Auxiliary\Build\vcvars64.bat'

$command = @(
    '"' + $vcvars + '"',
    '&&', 'cmake', '-S', '"' + $projectRoot + '"', '-B', '"' + $buildDir + '"', '-G', 'Ninja', '-DCMAKE_BUILD_TYPE=' + $Configuration,
    '&&', 'cmake', '--build', '"' + $buildDir + '"', '--config', $Configuration
) -join ' '

cmd.exe /d /s /c $command
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

