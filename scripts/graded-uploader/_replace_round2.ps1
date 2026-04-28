# One-shot wrapper for _replace_round2.py — pushes the 5 reprocessed
# graded-card images (Pikachu Van Gogh #2, Wobbuffet, Mega Dragonite,
# CGC Blastoise, Mewtwo GX) into Square via /admin/replace-graded-images.
# Token entered at a masked prompt, never on the command line.

$ErrorActionPreference = 'Stop'

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

$secure = Read-Host -Prompt 'Paste SK admin token (input is masked)' -AsSecureString
$ptr    = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $env:SK_ADMIN_TOKEN = [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
} finally {
    [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
}

python _replace_round2.py
$exit = $LASTEXITCODE

Remove-Item Env:SK_ADMIN_TOKEN -ErrorAction SilentlyContinue

exit $exit
