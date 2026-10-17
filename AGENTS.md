# DNS Unblock — Agent Guide

## Product purpose

A small Decky Loader plugin for Vietnamese Steam Deck owners that bypasses
ISP DNS blocking from Game Mode.

The intended experience is: enable it once, connect to Wi-Fi, and access
Steam without manually troubleshooting DNS providers.

Prioritize reliable connectivity, safe restoration, clear status, and a
simple controller-friendly UI. Keep features focused on this purpose.
This is not a VPN, a game-performance optimizer, or a general network manager.

## Start here

1. Check `git status --short`; preserve unrelated changes.
2. Read `README.md` for user-facing behavior and development commands.
3. Read `docs/spike-notes.md` for measured SteamOS/NetworkManager behavior.
4. Read `docs/field-test.md` to distinguish verified behavior from assumptions.
5. Inspect the relevant implementation and tests before editing.

Treat field notes as observations from the recorded environment, not universal
guarantees. Check current code before assuming a proposed feature has shipped.

## Code map

- `main.py`: Decky lifecycle, RPCs, reconciliation, DNS application/restoration,
  proxy recovery, status events, and crash-recovery markers.
- `py_modules/dns_unblock/state.py`: pure state decisions and fallback steps.
- `py_modules/dns_unblock/nm.py`: NetworkManager/systemd-resolved commands,
  output parsing, runtime DNS changes, and restoration.
- `py_modules/dns_unblock/proxy.py`: bundled dnsproxy process lifecycle.
- `py_modules/dns_unblock/watcher.py`: network events, debounce inputs,
  and monitor restart behavior.
- `py_modules/dns_unblock/health.py`, `httpscheck.py`, and `dnsquery.py`:
  DNS/HTTPS verification, diagnostics (Network/Provider/Deck/HTTPS), and
  DNS packets.
- `py_modules/dns_unblock/providers.py` and `settings.py`: provider presets,
  validation, defaults, and persistent settings.
- `src/index.tsx`: Quick Access panel, controls, diagnostics, and notifications.
- `src/api.ts`: frontend/backend contract, labels, and selectable options.
- `tests/`: backend tests; review lifecycle coverage as well as helper tests.
- `.github/workflows/`: CI checks and release packaging.
- `scripts/`: deployment, pinned dnsproxy fetching, and investigative scripts.

Some search configurations omit `py_modules`; use `git ls-files` or a targeted
`rg --files --no-ignore py_modules` when locating backend files.

## Engineering rules

- Change DNS at runtime; do not persist overrides into saved Wi-Fi profiles.
- Preserve existing settings and explicit manual provider choices.
- Restore DNS before stopping a resolver that the active link still needs.
- Keep recovery records until restoration succeeds or the device is confirmed
  inactive. Report failures honestly.
- Keep subprocesses and network probes bounded, cancellable, and cleaned up.
- Do not kill unrelated processes or apply results from an obsolete connection.
- Keep healthy operation event-driven. Bound and back off recovery retries.
- Maintain IPv4/IPv6 handling and captive-portal compatibility.
- Keep subprocess execution argument-based; preserve locale and environment
  handling in `nm.py`.
- Keep the Python backend standard-library-only unless a task explicitly
  justifies a dependency. Preserve binary checksum pinning and license notices.
- Update backend payloads and `src/api.ts` together.
- Preserve UI state needed across Decky panel/dropdown remounts.

## Diagnose the right layer

Separate these questions:
1. Can the chosen resolver be reached?
2. Does it return usable DNS answers?
3. Can the Deck connect to the returned Steam endpoints?
4. Does Steam itself work?

A successful DNS lookup does not prove Steam works.
A timeout or SERVFAIL does not prove ISP blocking.
A running dnsproxy does not prove the system is using encrypted DNS.

Users have reported FPT connections working after switching to Google despite
apparently healthy diagnostics. The cause is unconfirmed; switching providers
also restarts the proxy. Do not hardcode ISP-to-provider assumptions.

Before changing selection behavior, inspect whether Auto means transport
fallback or provider selection. Before trusting diagnostics, inspect which
provider and resolver they actually test.

Compare providers on the same connection and record mode, configured provider,
actual resolver, lookup results, connection results, and timestamps.
Never diagnose Proton/game-launch failures from DNS evidence alone.

## Local verification

Use Python 3.11 compatibility and the pnpm version pinned in `package.json`.
CI currently uses Node 20; follow the workflow for reproducible checks.

    pnpm install --frozen-lockfile
    python -m unittest discover -s tests -t . -v
    pnpm exec tsc --noEmit --skipLibCheck
    pnpm run build

For behavior changes, add regression tests at the layer where failure occurs.
Pure state/parser tests do not replace lifecycle and recovery tests.

Cover relevant failure paths: restore failure, provider timeout, secondary
server success, proxy exit, settings changes, reconnect during a probe,
stale results, and shutdown during reconciliation.

Documentation-only changes require checking paths, commands, and claims;
they do not require running the full build.

## Steam Deck verification

Windows tests cannot establish actual SteamOS networking behavior.
Use `docs/field-test.md` for device validation.

For network changes, verify home Wi-Fi, hotspot, switching, sleep/wake,
Wi-Fi off/on, captive portals, offline networks, and provider/mode changes.
For lifecycle changes, verify disable, Decky restart, reboot, and uninstall.
For UI changes, verify controller focus, dropdown remounts, readable errors,
and panel reopening.

Inspect:
- Plugin logs and `dnsproxy.log` under
  `~/homebrew/logs/decky-dns-unblock/`.
- `resolvectl dns <device>` and `resolvectl status <device>`.
- `nmcli monitor` and actual Steam access.

Use `scripts/deploy.ps1` for an authorized device deployment.
It installs plugin files and restarts Decky. Keep `.env.ps1` private.
Never mark an unperformed field test as passed.

## Finish cleanly

Update README/changelog when user-visible behavior changes.
Keep detailed field evidence in the docs rather than expanding this guide.

Report what changed, checks passed, checks not performed, and remaining risks.
Do not claim an ISP issue is fixed without testing an affected connection.
Do not deploy, push tags, or publish a release unless the task authorizes it.
