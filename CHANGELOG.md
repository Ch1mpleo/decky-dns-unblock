# Changelog

## [0.2.0] - 2026-10-18

Reliability release: Automatic provider selection with DNS + HTTPS checks, safer restore,
honest diagnostics, and clearer status.

### Features

- **Provider Automatic** (default on new installs): try Cloudflare → Google → Quad9 (then plain
  backups in Auto mode). Saved 0.1.0 providers (e.g. Cloudflare) are **not** remapped on upgrade.
- Selection verifies **Steam DNS and HTTPS** (SNI/Host) before committing a provider. DNS-only
  success can stay applied with “Steam unverified”; full failure falls back to network DNS.
- Status shows the active provider and transport (e.g. `Active · Google · Encrypted`).
- Diagnostics columns: **Network / Provider / Deck / HTTPS** against the active or configured
  resolver (not a fixed Cloudflare DoH probe). Sticky results clear when mode/provider/device changes.

### Fixes

- Restore marker cleared only after a successful restore; unload retries restore before stopping
  dnsproxy; startup restores before killing a leftover proxy the link may still need.
- Generation guards discard stale apply/diagnostics work after reconnect or settings changes.
- Two-failure hysteresis before replacing an established provider; 60 s health reuse on panel open.
- Probe dnsproxy on ports 15353–15355 for selection/diagnostics without touching live link DNS.
- Plain mode tests each server independently and applies only verified addresses.
- Auto mode still keeps a plain provider IP as link backup behind dnsproxy.

### Tests / CI

- Plugin lifecycle tests for Automatic failover, fallback, diagnostics cancel, shutdown restore.
- Release workflow runs the same TypeScript check as CI before packaging.

### Field notes

- VNPT / Viettel behaviour from 0.1.0 still applies as a baseline.
- **FPT is not claimed fixed** without affected-user Steam confirmation on that ISP.
  Compare Automatic vs Cloudflare vs Google on the same link (see `docs/field-test.md`).

## [0.1.0] - 2026-10-13

First release.

### Features

- Quick Access panel: on/off toggle, Mode (Auto / Encrypted only / Plain only), Provider (Cloudflare, Google,
  Quad9, Custom), live status with Wi-Fi, link DNS and the server in use, toasts for Paused / Fallback / Error.
- Encrypted DNS through a bundled, checksum-pinned AdGuard dnsproxy v0.86.0 on `127.0.0.2:53`, using IP-address
  DoH upstreams so nothing is looked up through the ISP's DNS.
- Safe fallback chain: encrypted -> plain public DNS -> the network's own DNS. Each step is verified by resolving
  `store.steampowered.com` before the Wi-Fi link is changed.
- Diagnostics: Steam domains checked against the network's DNS, Cloudflare DoH and the Deck's resolver, with a
  plain-language summary.

### Network handling

- Event-driven (`nmcli monitor`), no polling: re-applies after Wi-Fi off/on, sleep/wake and network switches,
  including Steam's delete-and-recreate of Wi-Fi profiles.
- Waits for NetworkManager's internet check after connecting (up to 10 s; ~6 s on a 4G hotspot) before applying.
- Captive portals: pauses and restores the network's DNS so the login page loads, resumes after login.
- dnsproxy is restarted after every reconnect: its pooled HTTPS connections from the previous network are dead and
  its cache would hide that (found switching from home Wi-Fi to a phone hotspot).
- dnsproxy crash -> restart and re-apply; 3 crashes -> plain DNS until the next connection or settings change.
- The resolver drifting to the backup server after a proxy hiccup is corrected when the panel is opened.

### Safety

- Runtime-only changes (`nmcli device modify` / `reapply`): saved Wi-Fi profiles are never edited, a reconnect or
  reboot always restores normal DNS.
- Crash cleanup on start (leftover DNS and dnsproxy), full restore on disable, unload and uninstall.
- IPv6-disabled profiles fall back to IPv4-only DNS settings.

### Verified

- VNPT home fiber (ISP DNS answers NXDOMAIN for Steam): Active - Encrypted, Steam resolves.
- Viettel 4G phone hotspot (same NXDOMAIN block): Active - Encrypted after the ~6 s internet check, Steam resolves.
- Wi-Fi off/on, sleep/wake, home <-> hotspot switching, mode/provider changes, killing dnsproxy.
