# Milestone 1 spike notes

Run on 2026-10-13 on the home Wi-Fi (`HuuTam_A3_5G`, VNPT, double NAT behind `192.168.1.1`).
SteamOS 3.8.28 (build 20260922.1), NetworkManager 1.52.1, systemd 257, system Python 3.13.5, Decky Loader v3.2.10.
Scripts: `scripts/spike/m1-spike.sh` (root checks, always restores DNS on exit) and `scripts/spike/nm-monitor.sh`.

## 1. ISP block style: NXDOMAIN

Queried with `py_modules/dns_unblock/dnsquery.py` straight at each server:

| Name | Router `192.168.1.1` / VNPT `123.23.23.23` | `1.1.1.1` / `8.8.8.8` (plain UDP 53) |
|---|---|---|
| store.steampowered.com, steamcommunity.com, api/login.steampowered.com, www.reddit.com | NXDOMAIN (A and AAAA) | real IPs |
| medium.com, google.com | real IPs | real IPs |

- Blocking is a fake NXDOMAIN from the ISP resolver, not a bogus IP and not a timeout.
- Plain DNS to public resolvers is not intercepted on this network, so "Plain" mode really works here.
  Other networks (4G, cafes) still need checking during the field test.
- DHCP hands out `domain_name_servers = 192.168.1.1 123.23.23.23`. Read it with
  `nmcli -t -f DHCP4.OPTION device show wlan0` and match `^DHCP4\.OPTION\[N\]:domain_name_servers = `
  (`-g` joins all options with ` | ` on one line, and `requested_domain_name_servers = 1` also exists).

## 2. Runtime override: `nmcli device modify` / `reapply`

```bash
nmcli device modify wlan0 ipv4.dns 9.9.9.9 ipv4.ignore-auto-dns yes ipv6.dns 2620:fe::fe ipv6.ignore-auto-dns yes
nmcli device reapply wlan0
```

- `modify` takes about 20 ms and prints `Connection successfully reapplied to device 'wlan0'.`; the link stays `100 (connected)`.
- The saved profile is untouched (`ipv4.dns` unchanged), so it's runtime-only, as intended.
- `resolvectl dns wlan0` showed only `9.9.9.9`. The IPv6 server was not pushed because this network only has a
  link-local IPv6 address. Still set `ipv6.dns` / `ipv6.ignore-auto-dns` so IPv6 networks can't leak ISP DNS.
- `reapply` (about 25 ms) restores whatever the saved profile says.
- Every `modify` / `reapply` restarts DHCP (`dhcp4: no lease` -> `new lease`, same address, ~100-200 ms). Harmless,
  but avoid re-applying when nothing changed.
- `reapply` fails with `Device is not activated` while Wi-Fi is down or reconnecting (seen in the audit log).
  `restore()` must treat that as success: a fresh activation uses the profile anyway.

## 3. dnsproxy on 127.0.0.2 behind systemd-resolved

```bash
dnsproxy -l 127.0.0.2 -p 53 -u https://1.1.1.1/dns-query -u https://8.8.8.8/dns-query --upstream-mode parallel --cache
nmcli device modify wlan0 ipv4.dns 127.0.0.2,1.1.1.1 ipv4.ignore-auto-dns yes ipv6.dns "" ipv6.ignore-auto-dns yes
```

- Port 53 before starting: only resolved on `127.0.0.53` and `127.0.0.54`, so `127.0.0.2:53` (and `127.0.0.1:53`) are free.
- resolved accepts a loopback link DNS server. `resolvectl query` went through dnsproxy (seen in its log),
  `getent` returned the real Steam IP, and `curl https://store.steampowered.com/` returned 200.
- First lookups took 125-150 ms. dnsproxy logs `HTTP3 support is not enabled` and uses HTTP/2. That's expected.
- dnsproxy v0.86.0 exits with status 0 on SIGTERM.
- **Killing dnsproxy**: the next lookups went to `1.1.1.1` within ~50 ms, so DNS kept working.
  But resolved then *stays* on `1.1.1.1` (`Current DNS Server: 1.1.1.1`) even after dnsproxy is back.
  - After restarting dnsproxy, re-run `device modify` so resolved starts from `127.0.0.2` again.
  - resolved can also switch on a single dnsproxy hiccup, so the status shown to the user should come from
    `Current DNS Server` in `resolvectl status wlan0`, not just from "dnsproxy is running".

## 4. SteamOS behaviour that affects the design

- **Game Mode recreates Wi-Fi profiles.** Picking a network in Steam's Wi-Fi menu runs `connection-delete` +
  `connection-add` (new UUID) from the `steam` process, then `connection-update`. Anything stored in the profile,
  such as a manual DNS setting, is wiped. This is how the manual 1.1.1.1 setting (Option A) disappeared.
  The plugin must key on the device (`wlan0`), never the profile UUID, and re-apply after every activation.
- Turning Wi-Fi off/on in Game Mode shows up as `audit: op="radio-control" arg="wireless-enabled:off|on"`.
- Sleep: `device (wlan0): state change: activated -> deactivating (reason 'sleeping')` at suspend.
  After resume, wlan0 is `activated` again about 2 s after `PM: suspend exit`.
- `KillUserProcesses=True` (`/etc/systemd/logind.conf.d/killuserprocesses.conf`): anything started from an SSH
  session dies when the session ends. This doesn't affect the plugin (it runs under the `plugin_loader` system service),
  but dev tooling must use `systemd-run --user`.
- NetworkManager polkit over SSH: `network-control` / `settings.modify.*` are `auth`, so manual tests need `sudo`.
- `nmcli monitor` output reaches a pipe line by line (the first line arrived before the process was killed).
  Re-check this in the M4 watcher.

## 5. `nmcli monitor` event lines

Recorded with `nm-monitor.sh` (timestamps added by the script). Steam's own `connection profile changed` noise removed.

Wi-Fi off / on (Game Mode toggle):

```text
03:16:05.607 wlan0: unavailable
03:16:05.611 There's no primary connection
03:16:05.615 Networkmanager is now in the 'disconnected' state
03:16:05.619 Connectivity is now 'none'
03:16:22.345 wlan0: disconnected
03:16:23.683 wlan0: using connection 'HuuTam_A3_5G'
03:16:23.686 wlan0: connecting (prepare)
03:16:23.693 wlan0: connecting (configuring)
03:16:23.916 wlan0: connecting (getting IP configuration)
03:16:24.067 'HuuTam_A3_5G' is now the primary connection
03:16:24.080 wlan0: connecting (checking IP connectivity)
03:16:24.106 wlan0: connecting (starting secondary connections)
03:16:24.110 wlan0: connected
03:16:24.114 Networkmanager is now in the 'connected (site only)' state
03:16:24.765 Networkmanager is now in the 'connected' state
03:16:24.768 Connectivity is now 'full'
```

Sleep / wake (~25 s asleep). On wake the sequence is the same as Wi-Fi on (`unavailable` -> `disconnected` -> ... -> `full`):

```text
03:16:44.292 Networkmanager is now in the 'asleep' state
03:16:44.296 wlan0: deactivating
03:16:44.471 wlan0: disconnected
03:16:44.474 There's no primary connection
03:16:44.482 wlan0: unmanaged
03:16:44.490 Connectivity is now 'none'
03:17:09.922 wlan0: unavailable
...
03:17:11.870 wlan0: connected
03:17:12.385 Connectivity is now 'full'
```

Switching networks in Game Mode (home -> phone hotspot). The profile is recreated first, then the device goes straight
from `connected` to `deactivating` with no `unavailable`:

```text
03:18:01.600 Nothing phone (Ch1mple): connection profile removed
03:18:01.610 Nothing phone (Ch1mple): connection profile created
03:18:01.617 wlan0: deactivating
03:18:01.842 wlan0: disconnected
03:18:01.853 wlan0: using connection 'Nothing phone (Ch1mple)'
03:18:01.867 Connectivity is now 'none'
...
03:18:03.520 wlan0: connected
03:18:03.524 Networkmanager is now in the 'connected (site only)' state
03:18:09.710 Networkmanager is now in the 'connected' state
03:18:09.714 Connectivity is now 'full'
```

Line patterns for the watcher:

| Pattern | Meaning |
|---|---|
| `^(\S+): connected$` | device up (IP configured), connectivity may not be known yet |
| `^(\S+): (disconnected\|unavailable\|unmanaged\|deactivating)$` | device down |
| `^(\S+): using connection '(.*)'$` / `^(\S+): connecting \((.*)\)$` | activation in progress (ignore) |
| `^Connectivity is now '(full\|portal\|limited\|none\|unknown)'$` | connectivity change |
| `^Networkmanager is now in the '(.*)' state$` | note the lowercase "m"; `asleep` on suspend |
| `^'(.*)' is now the primary connection$` / `^There's no primary connection$` | primary changes |
| `: connection profile (changed\|created\|removed)$` | ignore |

Findings:
- `connected` comes before connectivity is known. At home `full` followed in ~0.6 s. On the phone hotspot it took
  **~6 s** (`connected (site only)` in between). So the plan's "on connected, wait for the connectivity event
  (timeout 10 s)" is needed. Check the 10 s timeout on slow cafe networks.
- `Connectivity is now 'none'` is emitted *during* a new activation, so `none` must not trigger a fallback by itself.
- **`connection profile changed` floods the output while Steam's Wi-Fi settings screen is open**: about one line per
  second for every saved profile in range (HuuTam_A3_5G, Container coffee, Nothing phone), 50-180 lines/min. This is
  the Steam client updating profiles during its scans. With the screen closed it stops completely (0 lines in 30 s).
  Cheap line filtering in the watcher is enough; no need to switch to `gdbus monitor`.
- The SSH shell runs with a POSIX locale; set `LC_ALL=C` for every `nmcli` call from the plugin so the English
  patterns above always match.
- No captive portal was available to test. `portal` handling stays unverified until the field test.
