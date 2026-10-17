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
| Mode | **Auto** (default): try encrypted DNS, then plain DNS, then network DNS. **Encrypted only**: encrypted candidates only; on failure restores network DNS (not a permanent “never plaintext” guarantee). **Plain only**: public DNS without dnsproxy. Mode Auto is **transport** fallback — it is not the same as Provider Automatic. |
| Provider | **Automatic** (default on new installs): try Cloudflare → Google → Quad9 (with DNS + HTTPS checks). Or pick one provider, or Custom (plain DNS only). Upgrading from 0.1.0 keeps a saved provider (e.g. Cloudflare is not remapped). |
| Run diagnostics | Per-domain Network / Provider / Deck DNS plus HTTPS to Steam (see below). |

### Status

When active, the label is concise: **Active · Provider · Transport** (e.g. `Active · Google · Encrypted`).
`(Steam unverified)` means DNS worked but HTTPS to Steam did not fully confirm.

| Status | Meaning |
|---|---|
| Active · … · Encrypted | DNS goes through dnsproxy (DoH). In Auto mode the link usually also keeps a plain provider IP as backup. |
| Active · … · Plain | Public DNS without encryption. Message may explain why (encrypted failed, custom servers, …). |
| Waiting for network | Just connected; waiting up to 10 s for the Deck's internet check before applying. |
| Paused - Wi-Fi login | A sign-in page was detected. Network DNS is restored so the login page loads; resumes after login. |
| Fallback - network DNS | No verified provider worked here; network DNS is restored (internet may work; blocked names can stay blocked). |
| No Wi-Fi connected / Off / Error | As it says. Errors also toast when the panel is closed. |

The panel table shows device, connectivity, link DNS, and the resolver in use. A successful DNS lookup does **not**
prove Steam works; open the store/community to confirm.

### Diagnostics

For `store.steampowered.com`, `steamcommunity.com`, `api.steampowered.com` and `login.steampowered.com`:

| Column | Asks |
|---|---|
| Network | Wi-Fi DHCP DNS — whether this network’s resolver fails Steam names |
| Provider | Active provider if running; otherwise the configured preference (Automatic may probe candidates without applying) |
| Deck | systemd-resolved (`127.0.0.53`) — whether the Deck path resolves Steam |
| HTTPS | TLS to Steam using provider-resolved addresses (SNI/Host) — DNS OK ≠ Steam reachable |

Summaries use measured phrases (DNS resolved / lookup failed / possible DNS blocking / HTTPS reachable /
access unverified). “Blocking” is only suggested when comparative evidence supports it (e.g. network NXDOMAIN
while the provider resolves). Sticky diagnostics clear when mode, provider, active provider, or device changes.

## How it behaves on different networks

The plugin reacts to NetworkManager events (`nmcli monitor`): it doesn't poll, so it costs nothing while
nothing changes. After each burst of events it re-reads the real state (connected Wi-Fi, internet check, current
DNS) and decides what to do, so a missed event can't leave it stuck. Before switching DNS it checks that the new
server actually resolves Steam, and only changes the link when the servers differ (every change briefly restarts DHCP).

### Home Wi-Fi (ISP DNS blocks Steam)

Tested on VNPT home fiber: the router hands out `192.168.1.1` and `123.23.23.23`, which answer `NXDOMAIN` for
Steam's domains and Reddit. Plain DNS to public resolvers is not intercepted there.

- Status becomes **Active · (provider) · Encrypted** after dnsproxy start + DNS/HTTPS verification (or dns_only
  if HTTPS does not confirm).
- In Auto mode, link DNS is `127.0.0.2` (dnsproxy) first and the provider's plain server second. If dnsproxy dies,
  the system resolver still has a working backup.
- Diagnostics (0.2.0): Network / Provider / Deck / HTTPS — see field notes in [docs/field-test.md](docs/field-test.md).
  FPT and similar “DNS OK, Steam broken” reports are **unconfirmed**; compare Automatic vs Cloudflare vs Google
  on the same link before assuming a provider fix.

### Phone hotspot (4G)

Tested on a Viettel 4G hotspot: its DNS (`10.109.83.145`) also answers `NXDOMAIN` for Steam; encrypted DNS gets through.

- The Deck's internet check takes about 6 s on a hotspot (`connected (site only)` first). The plugin shows
  **Waiting for network** until the check reports full internet, then applies, so it never fights the connection setup.
- dnsproxy is **restarted on every reconnect**. Its pooled HTTPS connections from the previous network are dead
  after a switch (requests would hang until timeout), and a fresh start also empties its cache so the verification
  lookup is real. Before this fix, switching from home Wi-Fi to the hotspot left Steam unresolvable while the status
  still said Active.

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
| Plugin disabled or uninstalled | Network DNS restored first (retries on unload), then dnsproxy stopped. If restore fails, the marker and proxy are kept for the next start. |
| IPv6-disabled profiles (Steam creates some) | IPv6 DNS settings are rejected there; the plugin retries with IPv4 only. |

## Safety and privacy

- Only runtime settings are changed (`nmcli device modify` / `reapply`); your saved Wi-Fi profiles are never edited.
- DoH upstreams are IP addresses (`https://1.1.1.1/dns-query`, ...), so no lookup ever goes through the ISP's DNS
  to find the DNS provider.
- The backend is Python standard library only; dnsproxy is an unmodified, checksum-pinned AdGuard release.
- No telemetry. Logs stay on the Deck in `~/homebrew/logs/decky-dns-unblock/`.

## Troubleshooting

- **Status stuck on Fallback:** run diagnostics. If Provider lookups fail while Network works, try another provider
  or Plain only. If Network already resolves Steam, Fallback may be harmless for Steam.
- **Steam still won't load but status is Active:** run diagnostics. If Provider/Deck DNS and HTTPS look fine, the
  problem may be beyond DNS (IP/SNI filtering, Steam client, account). Switching Automatic↔Google can help gather
  evidence; it also restarts the proxy. Do not assume FPT (or any ISP) is “fixed” from DNS alone.
- **Logs:** `~/homebrew/logs/decky-dns-unblock/` (plugin log per start, `dnsproxy.log` / probe logs).
- **Undo everything by hand:** toggle off, or `sudo nmcli device reapply wlan0`, or just reconnect the Wi-Fi.

### Support report template

Copy when filing an issue (omit MAC/SSID unless you choose to share them):

```text
Plugin version:
SteamOS / Decky version:
Mode (Auto / Encrypted / Plain):
Provider preference (Automatic / Cloudflare / …):
Active provider (from status):
Status line:
Diagnostics summary:
Network / Provider / Deck / HTTPS (per domain if useful):
ISP / connection type (home / hotspot / cafe):
Did Steam store or community load? (yes/no):
Time (local) and anything just changed (Wi-Fi switch, sleep, …):
```

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
