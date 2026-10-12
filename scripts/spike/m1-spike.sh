#!/bin/bash
# Milestone 1 on-device spike: ISP block style, runtime DNS override (nmcli device modify/reapply),
# and dnsproxy on 127.0.0.2 behind systemd-resolved. Always restores the network's DNS on exit.
#
# Expects dnsproxy and dnsquery.py (py_modules/dns_unblock/dnsquery.py) next to this script. Run on the Deck as root, detached from the
# terminal so a dropped SSH session can't interrupt it halfway:
#   sudo setsid bash m1-spike.sh; cat /tmp/m1-spike.log
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG=/tmp/m1-spike.log
PROXY_LOG=/tmp/m1-dnsproxy.log
exec >"$LOG" 2>&1

[ "$(id -u)" -eq 0 ] || { echo "must run as root"; exit 1; }

DEV=$(nmcli -t -f DEVICE,TYPE,STATE device | awk -F: '$2=="wifi" && $3=="connected" {print $1; exit}')
[ -n "$DEV" ] || { echo "no connected Wi-Fi device"; exit 1; }
CONN=$(nmcli -g GENERAL.CONNECTION device show "$DEV")
PROXY_PID=

cleanup() {
    [ -n "$PROXY_PID" ] && kill "$PROXY_PID" 2>/dev/null
    nmcli device reapply "$DEV"
    echo
    echo "===== cleanup: reapplied $DEV, link DNS now: $(resolvectl dns "$DEV")"
}
trap cleanup EXIT

ms() { date +%s%3N; }
step() { echo; echo "===== $(date +%T.%3N) $*"; }
q() { python3 "$DIR/dnsquery.py" "$@"; }
rq() {
    local t0; t0=$(ms)
    resolvectl query --cache=no --legend=no "$1" 2>&1 | head -n 3
    echo "  -> resolvectl query $1 took $(( $(ms) - t0 )) ms"
}

step "context"
echo "dev=$DEV conn=$CONN"
nmcli --version
resolvectl --version | head -n 1
nmcli -f ipv4.dns,ipv4.ignore-auto-dns,ipv6.dns,ipv6.ignore-auto-dns connection show "$CONN"
DHCP_DNS=$(nmcli -t -f DHCP4.OPTION device show "$DEV" | sed -n 's/^DHCP4\.OPTION\[[0-9]*\]:domain_name_servers = //p')
echo "DHCP DNS: $DHCP_DNS"
echo "link DNS: $(resolvectl dns "$DEV")"
echo "port 53 listeners:"
ss -lunp | grep ':53 '

step "1. block style via the network's DHCP DNS"
for s in $DHCP_DNS; do
    for d in store.steampowered.com steamcommunity.com; do
        echo "$s $d $(q "$s" "$d")"
    done
done

step "2a. runtime override: device modify -> 9.9.9.9 / 2620:fe::fe"
t0=$(ms)
nmcli device modify "$DEV" ipv4.dns 9.9.9.9 ipv4.ignore-auto-dns yes ipv6.dns 2620:fe::fe ipv6.ignore-auto-dns yes
echo "rc=$? took $(( $(ms) - t0 )) ms"
sleep 1
echo "link DNS: $(resolvectl dns "$DEV")"
echo "profile ipv4.dns (should be unchanged): $(nmcli -g ipv4.dns connection show "$CONN")"
nmcli -g GENERAL.STATE device show "$DEV"
rq store.steampowered.com

step "2b. restore: device reapply"
t0=$(ms)
nmcli device reapply "$DEV"
echo "rc=$? took $(( $(ms) - t0 )) ms"
sleep 1
echo "link DNS: $(resolvectl dns "$DEV")"
nmcli -g GENERAL.STATE device show "$DEV"
echo "connectivity: $(nmcli networking connectivity check)"

step "3a. start dnsproxy on 127.0.0.2:53"
"$DIR/dnsproxy" --version
"$DIR/dnsproxy" -l 127.0.0.2 -p 53 -u https://1.1.1.1/dns-query -u https://8.8.8.8/dns-query \
    --upstream-mode parallel --cache --verbose >"$PROXY_LOG" 2>&1 &
PROXY_PID=$!
sleep 2
if kill -0 "$PROXY_PID" 2>/dev/null; then echo "dnsproxy running (pid $PROXY_PID)"; else echo "dnsproxy DIED"; cat "$PROXY_LOG"; PROXY_PID=; fi
echo "direct query: $(q 127.0.0.2 store.steampowered.com)"

step "3b. link DNS = 127.0.0.2, 1.1.1.1 (no IPv6 DNS)"
nmcli device modify "$DEV" ipv4.dns 127.0.0.2,1.1.1.1 ipv4.ignore-auto-dns yes ipv6.dns "" ipv6.ignore-auto-dns yes
echo "rc=$?"
sleep 1
echo "link DNS: $(resolvectl dns "$DEV")"
rq store.steampowered.com
rq steamcommunity.com
echo "getent: $(getent hosts store.steampowered.com)"
curl -s -o /dev/null -w 'curl https://store.steampowered.com/ -> %{http_code} in %{time_total}s\n' https://store.steampowered.com/
echo "dnsproxy log lines mentioning steam: $(grep -ci steam "$PROXY_LOG")"

step "3c. kill dnsproxy: resolved should fall over to 1.1.1.1"
kill "$PROXY_PID"; wait "$PROXY_PID" 2>/dev/null; echo "dnsproxy exit status $?"; PROXY_PID=
rq login.steampowered.com
rq api.steampowered.com
echo "link DNS / current server: $(resolvectl dns "$DEV") / $(resolvectl status "$DEV" | sed -n 's/.*Current DNS Server: //p')"

step "3d. dnsproxy log (last 25 lines)"
tail -n 25 "$PROXY_LOG"
