<#
.SYNOPSIS
Download the pinned AdGuard dnsproxy Linux build into bin/ and verify its checksum.
The version and checksum live in scripts/dnsproxy.pin (shared with fetch-dnsproxy.sh used by CI).
#>
$ErrorActionPreference = 'Stop'

$pin = Get-Content (Join-Path $PSScriptRoot 'dnsproxy.pin') -Raw | ConvertFrom-StringData
$Version = $pin.version
$Sha256 = $pin.sha256
$Asset = "dnsproxy-linux-amd64-$Version.tar.gz"
$Url = "https://github.com/AdguardTeam/dnsproxy/releases/download/$Version/$Asset"

$root = Split-Path -Parent $PSScriptRoot
$bin = Join-Path $root 'bin'
$work = Join-Path $env:TEMP "dnsproxy-$Version"
$archive = Join-Path $env:TEMP $Asset

try {
    Invoke-WebRequest -Uri $Url -OutFile $archive -UseBasicParsing
    $actual = (Get-FileHash -Algorithm SHA256 $archive).Hash.ToLower()
    if ($actual -ne $Sha256) { throw "Checksum mismatch for ${Asset}: got $actual" }

    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $work
    New-Item -ItemType Directory -Force $work, $bin | Out-Null
    tar -xzf $archive -C $work
    if ($LASTEXITCODE) { throw 'Extracting failed' }

    Copy-Item -Force (Join-Path $work 'linux-amd64\dnsproxy') (Join-Path $bin 'dnsproxy')
    Copy-Item -Force (Join-Path $work 'linux-amd64\LICENSE') (Join-Path $bin 'dnsproxy.LICENSE')
    Write-Host "dnsproxy $Version -> $bin"
}
finally {
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $work, $archive
}
