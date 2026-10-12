<#
.SYNOPSIS
Build the plugin and install it on the Steam Deck over SSH, then restart Decky.

.DESCRIPTION
Reads $DeckHost / $DeckUser from the gitignored .env.ps1 at the repo root.
The plugin folder on the Deck is root-owned, so the files are uploaded to /tmp
and moved into place with sudo (you are asked for the Deck password once per run).
#>
param(
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

$envFile = Join-Path $root '.env.ps1'
if (-not (Test-Path $envFile)) {
    throw "Missing .env.ps1. Copy .env.ps1.example to .env.ps1 and set `$DeckHost."
}
. $envFile
if (-not $DeckHost) { throw '$DeckHost is not set in .env.ps1' }
if (-not $DeckUser) { $DeckUser = 'deck' }

$name = (Get-Content (Join-Path $root 'package.json') -Raw | ConvertFrom-Json).name
if (-not $name) { throw 'Could not read the plugin name from package.json' }
$target = "$DeckUser@$DeckHost"
$archive = Join-Path $env:TEMP "$name.tar.gz"

Push-Location $root
try {
    if (-not $SkipBuild) {
        pnpm run build
        if ($LASTEXITCODE) { throw 'Frontend build failed' }
    }

    $items = @('dist', 'main.py', 'py_modules', 'plugin.json', 'package.json', 'LICENSE')
    if (Test-Path 'bin') { $items += 'bin' }

    tar -czf $archive --exclude=__pycache__ @items
    if ($LASTEXITCODE) { throw 'Packing failed' }

    scp -q $archive "${target}:/tmp/$name.tar.gz"
    if ($LASTEXITCODE) { throw 'Upload failed' }

    $pluginDir = "/home/$DeckUser/homebrew/plugins/$name"
    $remote = @(
        'set -e'
        "sudo rm -rf $pluginDir"
        "sudo mkdir -p $pluginDir"
        "sudo tar -xzf /tmp/$name.tar.gz -C $pluginDir --no-same-owner"
        # Windows tar stores everything as world-writable; the backend runs as root.
        "sudo chmod -R u=rwX,go=rX $pluginDir"
        "if [ -d $pluginDir/bin ]; then sudo chmod 755 $pluginDir/bin/*; fi"
        "rm -f /tmp/$name.tar.gz"
        'sudo systemctl restart plugin_loader'
        "echo Deployed to $pluginDir"
    ) -join '; '

    ssh -t $target $remote
    if ($LASTEXITCODE) { throw 'Install on the Deck failed' }
}
finally {
    Remove-Item -ErrorAction SilentlyContinue $archive
    Pop-Location
}
