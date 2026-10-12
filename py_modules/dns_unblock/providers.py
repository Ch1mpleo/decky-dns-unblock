"""DNS provider presets. IP-literal DoH URLs so no bootstrap lookup ever goes through the ISP's DNS."""

import ipaddress
from dataclasses import dataclass


@dataclass(frozen=True)
class Provider:
    label: str
    v4: tuple[str, ...]
    v6: tuple[str, ...]
    doh: tuple[str, ...]


PROVIDERS: dict[str, Provider] = {
    "cloudflare": Provider(
        "Cloudflare",
        ("1.1.1.1", "1.0.0.1"),
        ("2606:4700:4700::1111", "2606:4700:4700::1001"),
        ("https://1.1.1.1/dns-query", "https://1.0.0.1/dns-query"),
    ),
    "google": Provider(
        "Google",
        ("8.8.8.8", "8.8.4.4"),
        ("2001:4860:4860::8888", "2001:4860:4860::8844"),
        ("https://8.8.8.8/dns-query", "https://8.8.4.4/dns-query"),
    ),
    "quad9": Provider(
        "Quad9",
        ("9.9.9.9", "149.112.112.112"),
        ("2620:fe::fe", "2620:fe::9"),
        ("https://9.9.9.9/dns-query", "https://149.112.112.112/dns-query"),
    ),
}
CUSTOM = "custom"


def split_servers(servers: list[str]) -> tuple[list[str], list[str]]:
    """Validate plain DNS server IPs and split them into (IPv4, IPv6). Raises ValueError on bad input."""
    v4: list[str] = []
    v6: list[str] = []
    for raw in servers:
        try:
            ip = ipaddress.ip_address(raw.strip())
        except ValueError:
            raise ValueError(f"Not an IP address: {raw!r}") from None
        if ip.is_loopback or ip.is_unspecified or ip.is_multicast:
            raise ValueError(f"Not usable as a DNS server: {raw!r}")
        target = v4 if ip.version == 4 else v6
        if str(ip) not in target:
            target.append(str(ip))
    if not v4 and not v6:
        raise ValueError("At least one DNS server is required")
    return v4, v6


def plain_servers(provider: str, custom_servers: list[str]) -> tuple[list[str], list[str]]:
    if provider == CUSTOM:
        return split_servers(custom_servers)
    preset = PROVIDERS[provider]
    return list(preset.v4), list(preset.v6)


def doh_upstreams(provider: str) -> list[str]:
    """DoH URLs for dnsproxy; custom servers are plain DNS only, so they have none."""
    preset = PROVIDERS.get(provider)
    return list(preset.doh) if preset else []
