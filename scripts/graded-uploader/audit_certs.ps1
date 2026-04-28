# Wrapper to run audit_certs.py with the admin token sourced from a
# masked prompt rather than the command line. The token never lands in
# shell history or the process list.

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

python audit_certs.py
$exit = $LASTEXITCODE

Remove-Item Env:SK_ADMIN_TOKEN -ErrorAction SilentlyContinue

exit $exit
