<#
.SYNOPSIS
One-time setup: add your Windows SSH public key to the Deck so deploys don't ask for the SSH password.
#>
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

$envFile = Join-Path $root '.env.ps1'
if (-not (Test-Path $envFile)) {
    throw "Missing .env.ps1. Copy .env.ps1.example to .env.ps1 and set `$DeckHost."
}
. $envFile
if (-not $DeckUser) { $DeckUser = 'deck' }

$key = Join-Path $HOME '.ssh\id_ed25519'
if (-not (Test-Path "$key.pub")) {
    ssh-keygen -t ed25519 -f $key
}

# PowerShell pipes add CRLF line endings, so strip \r on the Deck side.
$remote = "umask 077; mkdir -p ~/.ssh; touch ~/.ssh/authorized_keys; tr -d '\r' > ~/.ssh/.newkey; " +
          "grep -qxFf ~/.ssh/.newkey ~/.ssh/authorized_keys || cat ~/.ssh/.newkey >> ~/.ssh/authorized_keys; " +
          "rm -f ~/.ssh/.newkey"
Get-Content "$key.pub" | ssh "$DeckUser@$DeckHost" $remote
if ($LASTEXITCODE) { throw 'Copying the key failed' }

ssh -o BatchMode=yes "$DeckUser@$DeckHost" 'echo Key login OK'
