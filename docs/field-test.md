# Field test checklist (0.2.0)

Run with a build that includes Automatic selection and DNS+HTTPS verification
(deployed plugin or release zip). Default for new installs: **Mode Auto**,
**Provider Automatic**.

**RC status (2026-10-18):** `0.2.0` deployed on Deck; local suite green. Home Wi‑Fi
(DHCP `116.97.90.124/127`, sinkhole block) + Viettel‑style hotspot (`10.94.20.45`,
NXDOMAIN) exercised with Provider **Automatic**:

- Home: Cloudflare Encrypted verified; diagnostics Network block · Provider/Deck/HTTPS OK.
- Hotspot: Cloudflare DNS OK but HTTPS timed out → Automatic selected **Google** Encrypted;
  diagnostics NXDOMAIN · Provider OK · HTTPS OK · Deck OK; Steam reported working.
- Switch home ↔ hotspot and sleep/wake re-applied cleanly (probe port 15353, then live `:53`).

Do **not** claim FPT fixed without an affected-user Steam pass on an FPT link.

For each network: open the panel, note Status (including active provider · transport),
then **Run diagnostics**. Collect logs afterward:

```bash
ls -t ~/homebrew/logs/decky-dns-unblock/2*.log | head -n 1
# also dnsproxy.log / dnsproxy-probe.log in the same directory
```

Status shorthand: **Enc** = Active · *Provider* · Encrypted, **Plain** = Active · *Provider* · Plain,
**FB** = Fallback - network DNS, **dns_only** = Enc/Plain with “(Steam unverified)”.

Do **not** mark an ISP “fixed” from DNS/HTTPS evidence alone — confirm Steam store/community
loads in Game Mode. **Do not mark FPT fixed** without an affected-user Steam confirmation.

## Provider comparison (same link)

On one connection, record Mode Auto for each provider preference. Fill DNS / HTTPS from diagnostics
(Provider + HTTPS columns) and note whether Steam UI actually works.

| ISP / network | Preference | Active provider | DNS (Provider) | HTTPS | Steam works? | Notes / time |
|---|---|---|---|---|---|---|
| VNPT home | Automatic | | | | | |
| VNPT home | Cloudflare | | | | | |
| VNPT home | Google | | | | | |
| Viettel 4G hotspot | Automatic | | | | | |
| Viettel 4G hotspot | Cloudflare | | | | | |
| Viettel 4G hotspot | Google | | | | | |
| FPT (affected link) | Automatic | | | | | unconfirmed — no “fixed” claim |
| FPT (affected link) | Cloudflare | | | | | |
| FPT (affected link) | Google | | | | | |

## Networks

| # | Network | Expected | Result |
|---|---|---|---|
| 1 | Home ISP Wi-Fi that blocks Steam (VNPT baseline) | Enc within ~1–2 s. Diagnostics: Network shows blocking evidence when present; Provider/Deck resolve; HTTPS reachable preferred. | [x] VNPT, 2026-10-13 (0.1.0 Enc/Cloudflare) · [ ] 0.2.0 Automatic recheck |
| 2 | Phone hotspot 4G (Viettel / Mobifone / Vinaphone) | Waiting a few seconds, then Enc. | [x] Viettel, 2026-10-13 · [ ] Mobifone · [ ] Vinaphone · [ ] 0.2.0 Automatic |
| 3 | FPT Wi-Fi (user-reported Steam fail with healthy DNS) | Record Automatic vs CF vs Google; Steam confirmation required. | [ ] — not claimed fixed |
| 4 | Cafe Wi-Fi, password only | Enc (or Plain/FB with a Note if DoH blocked). Steam store loads. | [ ] |
| 5 | Cafe / hotel / mall Wi-Fi with a login page | Paused - Wi-Fi login and a toast; login page opens; after login, Enc on its own. | [ ] |
| 6 | Wi-Fi without internet (router unplugged from WAN) | Waiting ~10 s, then FB. Toast. | [ ] |
| 7 | Network that blocks DoH / port 443 to public resolvers | Plain with encrypted-failed note, or FB if plain blocked too. | [ ] |

## Device events

| # | Action | Expected | Result |
|---|---|---|---|
| 8 | Wi-Fi off, wait, on | No Wi-Fi, then Enc ~2 s after reconnect; generation discard if mid-probe. | [x] 0.1.0 · [ ] 0.2.0 |
| 9 | Sleep 1+ min, wake | Enc again ~2 s after Wi-Fi is back. | [x] 0.1.0 · [ ] 0.2.0 |
| 10 | Switch network in Steam Wi-Fi menu (home ↔ hotspot) | Enc on each; diagnostics context matches new device. | [x] 0.1.0 · [ ] 0.2.0 |
| 11 | Reboot the Deck | Boots with normal DNS; Enc once Decky starts; no leftover broken marker. | [ ] |
| 12 | Decky restart (`sudo systemctl restart plugin_loader`) | Enc again; one dnsproxy (`pgrep -a dnsproxy`). | [x] deploys · [ ] 0.2.0 |
| 13 | `sudo pkill dnsproxy` once, then twice more | Back to Enc after 1st/2nd; Plain with crash note after 3rd. | [x] 0.1.0 · [ ] 0.2.0 |
| 14 | Toggle off | Off; `resolvectl dns wlan0` = network DNS; no dnsproxy. | [x] 0.1.0 · [ ] 0.2.0 |
| 15 | Uninstall the plugin | Same as toggle off; plugin dir gone. Restore-before-stop. | [ ] |

## Settings (0.2.0)

| # | Action | Expected | Result |
|---|---|---|---|
| 16 | Provider Automatic (new default) | Tries CF → Google → Quad9; status shows chosen active provider. | [ ] |
| 17 | Mode Plain only | Plain; link DNS = verified plain servers; no dnsproxy. | [x] 0.1.0 · [ ] 0.2.0 |
| 18 | Mode Encrypted only | Enc; link DNS is `127.0.0.2` only (no plain backup). On total fail → network DNS (not a no-plaintext guarantee forever). | [x] 0.1.0 · [ ] 0.2.0 |
| 19 | Provider Google / Quad9 manual | Enc with that provider (`dnsproxy.log` upstream URLs). | [ ] |
| 20 | Provider Custom in Auto | Plain; “Custom servers have no encrypted DNS”. | [x] 0.1.0 |
| 21 | Provider Custom in Encrypted only | FB with the same note. | [x] 0.1.0 |
| 22 | Upgrade from 0.1.0 with saved Cloudflare | Preference stays Cloudflare (not remapped to Automatic). | [ ] |
| 23 | Diagnostics while changing provider mid-run | Stale/cancelled summary; sticky UI clears on context change. | [ ] |

## When something is off

Note ISP, time, Mode, provider preference, **active provider**, Status, diagnostics summary
(Network / Provider / Deck / HTTPS), then grab plugin + dnsproxy logs. Prefer the support
template in the README. `nmcli monitor` events and state changes are in the plugin log.
