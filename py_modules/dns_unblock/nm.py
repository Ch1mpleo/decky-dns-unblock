"""NetworkManager / systemd-resolved helpers.

DNS is changed with `nmcli device modify` (runtime only: gone after reconnect or reboot) and undone with
`nmcli device reapply`, so a crashed plugin can never leave the Deck with broken DNS for long.
See docs/spike-notes.md for the observed command behaviour and output formats.
"""

import asyncio
import os
import re

NMCLI = "nmcli"
RESOLVECTL = "resolvectl"
DEFAULT_TIMEOUT = 10.0

CONNECTIVITY_STATES = ("full", "portal", "limited", "none", "unknown")


class CommandError(Exception):
    pass


def _env() -> dict[str, str]:
    env = dict(os.environ)
    # Decky's PyInstaller runtime points LD_LIBRARY_PATH at its bundled libs, which can break system binaries.
    original = env.pop("LD_LIBRARY_PATH_ORIG", None)
    if original:
        env["LD_LIBRARY_PATH"] = original
    else:
        env.pop("LD_LIBRARY_PATH", None)
    # Output parsing relies on the untranslated English messages.
    env["LC_ALL"] = "C"
    return env


async def run(*args: str, timeout: float = DEFAULT_TIMEOUT) -> tuple[int, str, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=_env()
        )
    except OSError as e:
        raise CommandError(f"{args[0]}: {e}") from e
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise CommandError(f"{' '.join(args[:3])} timed out after {timeout:.0f}s") from None
    return proc.returncode, out.decode(errors="replace"), err.decode(errors="replace")


async def run_ok(*args: str, timeout: float = DEFAULT_TIMEOUT) -> str:
    code, out, err = await run(*args, timeout=timeout)
    if code != 0:
        raise CommandError(f"{' '.join(args[:3])} failed ({code}): {(err or out).strip()}")
    return out


# --- parsers (pure, unit-tested) ---

def _split_terse(line: str) -> list[str]:
    """Split one `nmcli -t` line on unescaped colons."""
    return [field.replace("\\:", ":").replace("\\\\", "\\") for field in re.split(r"(?<!\\):", line)]


def parse_devices(text: str) -> list[tuple[str, str, str]]:
    """Parse `nmcli -t -f DEVICE,TYPE,STATE device` into (device, type, state) tuples."""
    devices = []
    for line in text.splitlines():
        fields = _split_terse(line)
        if len(fields) >= 3 and fields[0]:
            devices.append((fields[0], fields[1], fields[2]))
    return devices


def pick_wifi_device(devices: list[tuple[str, str, str]]) -> str | None:
    for name, dev_type, state in devices:
        if dev_type == "wifi" and state == "connected":
            return name
    return None


def parse_dhcp_dns(text: str) -> list[str]:
    """Parse `nmcli -t -f DHCP4.OPTION device show <dev>` for the DNS servers handed out by DHCP."""
    for line in text.splitlines():
        m = re.match(r"^DHCP4\.OPTION\[\d+\]:domain_name_servers = (.+)$", line.strip())
        if m:
            return m.group(1).split()
    return []


def parse_link_dns(text: str) -> list[str]:
    """Parse `resolvectl dns <dev>` ("Link 3 (wlan0): 1.1.1.1 8.8.8.8"), dropping any #server-name suffix."""
    _, sep, servers = text.strip().partition("):")
    if not sep:
        return []
    return [s.split("#", 1)[0] for s in servers.split()]


def parse_current_dns(text: str) -> str | None:
    """Parse `resolvectl status <dev>` for the server resolved is using right now."""
    m = re.search(r"Current DNS Server:\s*(\S+)", text)
    return m.group(1).split("#", 1)[0] if m else None


# --- commands ---

async def get_active_wifi_device() -> str | None:
    out = await run_ok(NMCLI, "-t", "-f", "DEVICE,TYPE,STATE", "device")
    return pick_wifi_device(parse_devices(out))


async def get_connectivity() -> str:
    out = await run_ok(NMCLI, "networking", "connectivity")
    state = out.strip()
    return state if state in CONNECTIVITY_STATES else "unknown"


async def get_dhcp_dns(device: str) -> list[str]:
    out = await run_ok(NMCLI, "-t", "-f", "DHCP4.OPTION", "device", "show", device)
    return parse_dhcp_dns(out)


async def get_link_dns(device: str) -> tuple[list[str], str | None]:
    """Return (configured link DNS servers, server currently in use)."""
    servers = parse_link_dns(await run_ok(RESOLVECTL, "dns", device))
    current = parse_current_dns(await run_ok(RESOLVECTL, "status", device))
    return servers, current


async def apply_dns(device: str, v4: list[str], v6: list[str]) -> None:
    """Replace the device's DNS servers at runtime (the saved Wi-Fi profile is not touched).

    The network's own (DHCP / router advertisement) DNS is ignored on both IP versions so the ISP's resolver
    can't leak back in. An empty list leaves that IP version without DNS servers.
    """
    v4_args = ["ipv4.dns", ",".join(v4), "ipv4.ignore-auto-dns", "yes"]
    v6_args = ["ipv6.dns", ",".join(v6), "ipv6.ignore-auto-dns", "yes"]
    try:
        await run_ok(NMCLI, "device", "modify", device, *v4_args, *v6_args)
    except CommandError as e:
        # Profiles with IPv6 disabled can reject ipv6.* properties; IPv4 alone is still worth applying.
        if "ipv6" not in str(e):
            raise
        await run_ok(NMCLI, "device", "modify", device, *v4_args)


async def restore(device: str) -> None:
    """Drop runtime changes and go back to the saved profile's settings (normally the network's own DNS)."""
    code, out, err = await run(NMCLI, "device", "reapply", device)
    message = (err or out).strip()
    # A device that is down or gone has nothing to undo: its next activation uses the profile anyway.
    if code != 0 and "not activated" not in message and "not found" not in message:
        raise CommandError(f"nmcli device reapply {device} failed ({code}): {message}")
