#!/bin/bash
# Download the pinned AdGuard dnsproxy Linux build into bin/ and verify its checksum (used by CI).
# Same pin as fetch-dnsproxy.ps1: scripts/dnsproxy.pin.
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
root=$(dirname "$here")
# shellcheck source=dnsproxy.pin
. "$here/dnsproxy.pin"

asset="dnsproxy-linux-amd64-${version}.tar.gz"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

curl -fsSL -o "$work/$asset" "https://github.com/AdguardTeam/dnsproxy/releases/download/${version}/${asset}"
echo "${sha256}  $work/$asset" | sha256sum -c -
tar -xzf "$work/$asset" -C "$work"

mkdir -p "$root/bin"
install -m 755 "$work/linux-amd64/dnsproxy" "$root/bin/dnsproxy"
install -m 644 "$work/linux-amd64/LICENSE" "$root/bin/dnsproxy.LICENSE"
echo "dnsproxy ${version} -> $root/bin"
