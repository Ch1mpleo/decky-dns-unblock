# DNS Unblock (decky-dns-unblock)

A [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) plugin for the Steam Deck that gets around
ISP DNS blocking (Steam store, community, login, Reddit, Medium, ...) on any Wi-Fi: home, phone hotspot, cafes, hotels.

It switches the Deck to encrypted DNS (DNS over HTTPS through a bundled
[dnsproxy](https://github.com/AdguardTeam/dnsproxy)), falls back to plain public DNS when encrypted DNS can't get
through, and falls back to the network's own DNS when neither works, so it never makes your internet worse.
Everything happens in Game Mode from the Quick Access menu.

## Why

Vietnamese ISPs (and some others) block sites by lying in their DNS answers: their resolver says
`store.steampowered.com` does not exist (`NXDOMAIN`). The sites themselves are not blocked, only the name lookup.
Asking a different resolver over an encrypted connection gets the real address.

Changing DNS by hand in Steam's Wi-Fi settings does not stick: Game Mode deletes and recreates the Wi-Fi profile
whenever you pick a network, which wipes the setting. It also has to be redone for every network. This plugin
re-applies automatically every time the Deck connects.

## Install

1. Install [Decky Loader](https://decky.xyz) if you haven't.
2. Decky Settings -> General: turn on **Developer mode**.
3. Decky Settings -> Developer -> **Install Plugin from URL**, paste:
   `https://github.com/Ch1mpleo/decky-dns-unblock/releases/latest/download/decky-dns-unblock.zip`
4. Open the Quick Access menu (`...` button) -> plug icon -> **DNS Unblock**, turn on **Bypass Steam block**.

The plugin runs as root: it changes network settings and runs a local DNS server on `127.0.0.2:53`.

**To turn it off:** flip the toggle off. The network's own DNS is back within a second.
**To remove it:** Decky plugin list -> DNS Unblock -> Uninstall. DNS is restored and dnsproxy stopped first.

## Using it

| Control | What it does |
|---|---|
| Bypass Steam block | Master switch. |
| Mode | **Auto** (default): encrypted DNS, plain DNS if that fails, network DNS if both fail. **Encrypted only**: never sends DNS unencrypted; falls back to network DNS instead of plain. **Plain only**: public DNS without dnsproxy. Mode Auto is transport fallback, not provider picking. |
| Provider | **Automatic** (default on new installs): try Cloudflare, Google, then Quad9. Or pick Cloudflare, Google, Quad9, or Custom. Custom servers are plain DNS only (no encrypted DNS). Existing installs keep their saved provider. |
| Run diagnostics | Checks Steam's domains and explains what's blocked (see below). |

### Status

| Status | Meaning |
|---|---|
| Active - Encrypted | DNS goes through dnsproxy over HTTPS. "In use: dnsproxy (DoH)". |
| Active - Plain | Public DNS (e.g. 1.1.1.1) without encryption. The Note says why (encrypted DNS failed, custom servers, ...). |
| Waiting for network | Just connected; waiting up to 10 s for the Deck's internet check before applying. |
| Paused - Wi-Fi login | A sign-in page was detected. The network's DNS is used so the login page loads; DNS Unblock resumes after you log in. |
| Fallback - network DNS | Neither encrypted nor plain DNS worked here, so the network's own DNS is used (internet keeps working, blocked sites stay blocked). |
| No Wi-Fi connected / Off / Error | As it says. Errors are also shown as a toast. |

Under the status a small table shows the Wi-Fi device and internet check result, the DNS servers set on the link,
and the server actually in use. Paused, Fallback and Error also pop up as toasts when the panel is closed.

### Diagnostics

For `store.steampowered.com`, `steamcommunity.com`, `api.steampowered.com` and `login.steampowered.com`:

| Column | Asks |
|---|---|
| Network | the Wi-Fi's own DNS (from DHCP) - shows whether this network blocks Steam |
| DoH | Cloudflare over HTTPS, directly - shows whether encrypted DNS can get through on this network |
| Deck | the Deck's resolver right now - shows whether the fix is working |

Answers that are `NXDOMAIN`, `SERVFAIL`, a timeout, empty, or a sinkhole address (`0.0.0.0`, `127.x`, private IPs)
count as Blocked. A one-line summary explains the result, e.g. "Your network's DNS blocks Steam (NXDOMAIN). The
Deck resolves Steam correctly."

## How it behaves on different networks

The plugin reacts to NetworkManager events (`nmcli monitor`): it doesn't poll, so it costs nothing while
nothing changes. After each burst of events it re-reads the real state (connected Wi-Fi, internet check, current
DNS) and decides what to do, so a missed event can't leave it stuck. Before switching DNS it checks that the new
server actually resolves Steam, and only changes the link when the servers differ (every change briefly restarts DHCP).

### Home Wi-Fi (ISP DNS blocks Steam)

Tested on VNPT home fiber: the router hands out `192.168.1.1` and `123.23.23.23`, which answer `NXDOMAIN` for
Steam's domains and Reddit. Plain DNS to public resolvers is not intercepted there.

- Status becomes **Active - Encrypted** about half a second after the plugin starts or the Wi-Fi connects
  (dnsproxy start + verified lookup).
- Link DNS is `127.0.0.2` (dnsproxy) first and the provider's plain server (`1.1.1.1`) second. If dnsproxy ever
  dies, the system resolver still has a working server and the internet doesn't drop.
- Diagnostics: Network Blocked, DoH OK, Deck OK.

### Phone hotspot (4G)

Tested on a Viettel 4G hotspot: its DNS (`10.109.83.145`) also answers `NXDOMAIN` for Steam; DoH gets through.

- The Deck's internet check takes about 6 s on a hotspot (`connected (site only)` first). The plugin shows
  **Waiting for network** until the check reports full internet, then applies, so it never fights the connection setup.
- dnsproxy is **restarted on every reconnect**. Its pooled HTTPS connections from the previous network are dead
  after a switch (requests would hang until timeout), and a fresh start also empties its cache so the verification
  lookup is real. Before this fix, switching from home Wi-Fi to the hotspot left Steam unresolvable while the status
  still said Active.
- Diagnostics: Network Blocked, DoH OK, Deck OK.

### Switching networks, Wi-Fi off/on, sleep and wake

- Wi-Fi off/on and sleep/wake: re-applied about 2 s after the Deck reports full internet. dnsproxy is stopped while
  there's no network.
- Switching networks in Steam's Wi-Fi menu: Steam deletes and recreates the profile and reconnects within ~2 s.
  The plugin treats every disconnect as "our DNS is gone" and re-applies on the new connection, even when the
  switch is faster than its 2 s debounce.
- Settings are per plugin, not per network: one setup works on every Wi-Fi.

### Cafe / hotel Wi-Fi

- **Password-only Wi-Fi** behaves like home Wi-Fi.
- **Login (captive) portals**: when the Deck's internet check reports a portal, the plugin pauses and gives the
  network its own DNS back, so the sign-in page can load. After you log in the check reports full internet and the
  plugin resumes automatically.
- **Networks that block DoH or public DNS**: Auto mode drops to plain DNS, and to the network's DNS if plain is
  blocked too (Fallback, with a toast). A network that hijacks plain DNS (answers for 1.1.1.1 with its own blocked
  answers) fails the verification and also ends in Fallback rather than pretending to work.
- **Wi-Fi without internet**: if the internet check doesn't report full within 10 s, the plugin tries anyway; when
  nothing resolves it falls back to the network's DNS.

Portal and cafe behaviour is designed from NetworkManager's portal detection but has not been field-tested yet,
see [docs/field-test.md](docs/field-test.md).

### Problems the plugin handles for you

| Situation | What happens |
|---|---|
| dnsproxy crashes | Restarted within ~50 ms and DNS re-applied. After 3 crashes it switches to plain until the next connection or settings change. |
| The system resolver drifts to the backup server after a dnsproxy hiccup (it doesn't switch back by itself) | Opening the panel notices "In use" isn't dnsproxy and moves it back. |
| Decky or the plugin crashes / is killed | DNS changes are runtime-only, so the next reconnect or reboot restores the network's DNS. On the next start a leftover dnsproxy is killed and leftover DNS is cleaned up first. |
| Reboot | Saved Wi-Fi profiles were never changed, so the Deck boots with normal DNS; the plugin re-applies when Decky starts. |
| Plugin disabled or uninstalled | dnsproxy stopped and the network's DNS restored before unloading. |
| IPv6-disabled profiles (Steam creates some) | IPv6 DNS settings are rejected there; the plugin retries with IPv4 only. |

## Safety and privacy

- Only runtime settings are changed (`nmcli device modify` / `reapply`); your saved Wi-Fi profiles are never edited.
- DoH upstreams are IP addresses (`https://1.1.1.1/dns-query`, ...), so no lookup ever goes through the ISP's DNS
  to find the DNS provider.
- The backend is Python standard library only; dnsproxy is an unmodified, checksum-pinned AdGuard release.
- No telemetry. Logs stay on the Deck in `~/homebrew/logs/decky-dns-unblock/`.

## Troubleshooting

- **Status stuck on Fallback:** run diagnostics. If DoH is Blocked, the network blocks encrypted DNS; try Plain only
  or another provider. If Network is OK, the network doesn't block Steam and Fallback is harmless.
- **Steam still won't load but status is Active:** run diagnostics. If Deck is OK, the block isn't DNS (the ISP may
  block by IP or SNI); a VPN is needed for that.
- **Logs:** `~/homebrew/logs/decky-dns-unblock/` (plugin log per start, `dnsproxy.log` for the proxy).
- **Undo everything by hand:** toggle off, or `sudo nmcli device reapply wlan0`, or just reconnect the Wi-Fi.

## Development (Windows)

Requirements: Node.js 16.14+ and pnpm v9 (`package.json` pins `pnpm@9`; pnpm 10+ or Corepack switches to it
automatically), Python 3.11+ for the tests.

```powershell
pnpm i
pnpm run build
.\scripts\fetch-dnsproxy.ps1       # pinned dnsproxy into bin/ (scripts/dnsproxy.pin)
python -m unittest discover -s tests -t .
```

### Deploying to the Deck

1. On the Deck (Desktop Mode, Konsole): `passwd` (if no password is set), then `sudo systemctl enable --now sshd`.
2. On Windows: copy `.env.ps1.example` to `.env.ps1` and set `$DeckHost`. `steamdeck.local` survives DHCP changes
   but needs IPv6 link-local on the Wi-Fi profile; if it doesn't resolve, use the IP (`ip -4 addr show wlan0`)
   or reserve one in your router.
3. One time: `.\scripts\install-ssh-key.ps1` (asks for the Deck password once, then SSH uses your key).
4. Each change: `.\scripts\deploy.ps1` builds, uploads, installs to `~/homebrew/plugins/decky-dns-unblock`
   and restarts Decky (asks for the Deck `sudo` password). Use `-SkipBuild` to reuse the current `dist/`.

### Debugging

- Frontend: Decky Settings -> Developer -> enable "Allow remote CEF debugging", then open
  `chrome://inspect` on Windows and add `<deck-ip>:8081` as a target.
- Backend logs: `~/homebrew/logs/decky-dns-unblock/` on the Deck, or `journalctl -u plugin_loader -f`.
- Design notes and measured NetworkManager behaviour: [docs/spike-notes.md](docs/spike-notes.md).

### Releasing

1. Bump `version` in `package.json` and add a `## [x.y.z]` section to [CHANGELOG.md](CHANGELOG.md).
2. Commit, then `git tag vx.y.z && git push origin vx.y.z`.
3. The Release workflow checks the tag matches `package.json`, runs the tests, builds, fetches the pinned dnsproxy,
   and publishes `decky-dns-unblock.zip` with the changelog section as release notes.

## License

BSD-3-Clause, see [LICENSE](LICENSE). Bundled third-party software is listed in [THIRD_PARTY.md](THIRD_PARTY.md).
