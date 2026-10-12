# Field test checklist

Run with the release build (installed from the release zip URL), Mode Auto, provider Cloudflare, unless noted.
For each network: open the panel, note the Status and its table, then **Run diagnostics**.
Afterwards collect the log: `ls -t ~/homebrew/logs/decky-dns-unblock/2*.log | head -n 1` (and `dnsproxy.log`).

Status shorthand: **Enc** = Active - Encrypted, **Plain** = Active - Plain, **FB** = Fallback - network DNS.

## Networks

| # | Network | Expected | Result |
|---|---|---|---|
| 1 | Home ISP Wi-Fi (blocks Steam) | Enc within ~1 s of connecting. Diagnostics: Network Blocked, DoH OK, Deck OK. | [x] VNPT, 2026-10-13 |
| 2 | Phone hotspot 4G (Viettel / Mobifone / Vinaphone) | Waiting for a few seconds, then Enc. Diagnostics: Deck OK. | [x] Viettel, 2026-10-13 · [ ] Mobifone · [ ] Vinaphone |
| 3 | Cafe Wi-Fi, password only | Enc (or Plain/FB with a Note if the network blocks DoH). Steam store loads. | [ ] |
| 4 | Cafe / hotel / mall Wi-Fi with a login page | Paused - Wi-Fi login and a toast; the login page opens; after logging in, Enc on its own. | [ ] |
| 5 | Wi-Fi without internet (router unplugged from WAN) | Waiting for ~10 s, then FB. Toast. Nothing else breaks. | [ ] |
| 6 | Network that blocks DoH or port 443 to 1.1.1.1 (if found) | Plain with "Encrypted DNS failed" note, or FB if plain is blocked too. | [ ] |

## Device events

| # | Action | Expected | Result |
|---|---|---|---|
| 7 | Wi-Fi off, wait, on | No Wi-Fi connected, then Enc ~2 s after reconnect. | [x] |
| 8 | Sleep 1+ min, wake | Enc again ~2 s after Wi-Fi is back. | [x] |
| 9 | Switch network in Steam's Wi-Fi menu (home <-> hotspot) | Enc on each; diagnostics Deck OK right after switching. | [x] |
| 10 | Reboot the Deck | Boots with normal DNS, Enc once Decky has started. | [ ] |
| 11 | Decky restart (`sudo systemctl restart plugin_loader`) | Enc again; no second dnsproxy (`pgrep -a dnsproxy` shows one). | [x] (deploys) |
| 12 | `sudo pkill dnsproxy` once, then twice more | Back to Enc after 1st and 2nd; Plain with "dnsproxy keeps crashing" after 3rd. | [x] |
| 13 | Toggle off | Off; `resolvectl dns wlan0` shows the network's DNS; `pgrep dnsproxy` empty. | [x] |
| 14 | Uninstall the plugin | Same as toggle off; nothing left in `~/homebrew/plugins/decky-dns-unblock`. | [ ] |

## Settings

| # | Action | Expected | Result |
|---|---|---|---|
| 15 | Mode Plain only | Plain; link DNS is the provider's plain servers; no dnsproxy. | [x] |
| 16 | Mode Encrypted only | Enc; link DNS is `127.0.0.2` only. | [x] |
| 17 | Provider Google, Quad9 | Enc with that provider (`dnsproxy.log` start line shows its URLs). | [ ] |
| 18 | Provider Custom (e.g. `1.1.1.1, 9.9.9.9`) in Auto | Plain with "Custom servers have no encrypted DNS". | [x] |
| 19 | Provider Custom in Encrypted only | FB with the same note. | [x] |

## When something is off

Note the network type and ISP, the time, the Status table and diagnostics, then grab both logs. `nmcli monitor`
event lines and every state change are in the plugin log.
