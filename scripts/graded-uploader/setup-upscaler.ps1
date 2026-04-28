# Setup script for Real-ESRGAN, the AI upscaler used by the graded-card
# pipeline. Downloads the Windows ncnn-vulkan release zip from GitHub and
# extracts it into scripts/graded-uploader/upscaler/.
#
# Usage:
#   pwsh ./setup-upscaler.ps1     # or right-click -> Run with PowerShell
#
# After install, the next `python process_inbox.py` run will pick the
# binary up automatically.

param(
    [string]$Url = 'https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-windows.zip'
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'  # avoid IWR's slow progress UI

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$dest = Join-Path $here 'upscaler'
$exe  = Join-Path $dest 'realesrgan-ncnn-vulkan.exe'

if (Test-Path $exe) {
    Write-Host "Already installed at $exe"
    exit 0
}

New-Item -ItemType Directory -Force -Path $dest | Out-Null

$zip = Join-Path $env:TEMP 'realesrgan-windows.zip'
Write-Host "Downloading $Url"
Invoke-WebRequest -Uri $Url -OutFile $zip

Write-Host "Extracting to $dest"
Expand-Archive -Path $zip -DestinationPath $dest -Force
Remove-Item $zip

# Some archives nest a single folder; flatten if needed so the binary is
# directly at upscaler/realesrgan-ncnn-vulkan.exe.
if (-not (Test-Path $exe)) {
    $found = Get-ChildItem -Path $dest -Filter 'realesrgan-ncnn-vulkan.exe' -Recurse | Select-Object -First 1
    if ($found) {
        $src = Split-Path -Parent $found.FullName
        Get-ChildItem -Path $src | Move-Item -Destination $dest -Force
    }
}

if (-not (Test-Path $exe)) {
    Write-Error "Install failed: $exe not found after extraction"
    exit 1
}

Write-Host ""
Write-Host "Installed: $exe"
Write-Host "Models in: $(Join-Path $dest 'models')"
Write-Host ""
Write-Host "Next run of process_inbox.py will use it automatically."
