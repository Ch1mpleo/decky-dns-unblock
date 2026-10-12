<#
.SYNOPSIS
Download the pinned AdGuard dnsproxy Linux build into bin/ and verify its checksum.
#>
$ErrorActionPreference = 'Stop'

$Version = 'v0.86.0'
$Sha256 = '17ac43f76ebfcedf547c663f6f31aa70e68b8eb6fc41d2fc37d3bfe21a2ced66'
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
