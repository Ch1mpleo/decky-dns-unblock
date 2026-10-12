# DNS Unblock (decky-dns-unblock)

A [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) plugin for the Steam Deck that gets around
ISP DNS blocking (Steam, Reddit, Medium, ...) on any Wi-Fi. It uses encrypted DNS (DoH through a bundled
`dnsproxy`) and falls back to plain DNS or the network's default DNS, so it never makes the internet worse.

Work in progress.

## Development (Windows)

Requirements: Node.js 16.14+ and pnpm v9 (`package.json` pins `pnpm@9`; pnpm 10+ or Corepack switches to it automatically).

```powershell
pnpm i
pnpm run build
```

### Deploying to the Deck

1. On the Deck (Desktop Mode, Konsole): `passwd` (if no password is set), then `sudo systemctl enable --now sshd`.
2. On Windows: copy `.env.ps1.example` to `.env.ps1`. The default `$DeckHost = 'steamdeck.local'` keeps working
   when the Deck's IP changes; fall back to the IP (`ip -4 addr show wlan0`) only if `.local` doesn't resolve.
3. One time: `.\scripts\install-ssh-key.ps1` (asks for the Deck password once, then SSH uses your key).
4. Each change: `.\scripts\deploy.ps1` builds, uploads, installs to `~/homebrew/plugins/decky-dns-unblock`
   and restarts Decky (asks for the Deck `sudo` password). Use `-SkipBuild` to reuse the current `dist/`.

### Debugging

- Frontend: Decky Settings -> Developer mode -> enable "Allow remote CEF debugging", then open
  `chrome://inspect` on Windows and add `<deck-ip>:8081` as a target.
- Backend logs: `~/homebrew/logs/decky-dns-unblock/` on the Deck, or `journalctl -u plugin_loader -f`.

## License

BSD-3-Clause, see [LICENSE](LICENSE). Bundled third-party software is listed in [THIRD_PARTY.md](THIRD_PARTY.md).
