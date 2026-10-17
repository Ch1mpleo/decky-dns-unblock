"""DNS provider presets. IP-literal DoH URLs so no bootstrap lookup ever goes through the ISP's DNS."""

import ipaddress
from dataclasses import dataclass

# Transport kinds used by Candidate (same strings as state.ENCRYPTED / state.PLAIN).
ENCRYPTED = "encrypted"
PLAIN = "plain"

AUTOMATIC = "automatic"
CUSTOM = "custom"
# Order for Automatic provider selection (and docs).
PRESET_ORDER = ("cloudflare", "google", "quad9")


@dataclass(frozen=True)
class Provider:
    label: str
    v4: tuple[str, ...]
    v6: tuple[str, ...]
    doh: tuple[str, ...]


@dataclass(frozen=True)
class Candidate:
    """One apply/evaluation attempt: a concrete provider + transport with its servers."""

    provider_id: str
    transport: str
    doh: tuple[str, ...] = ()
    v4: tuple[str, ...] = ()
    v6: tuple[str, ...] = ()


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


def is_valid_provider(provider: str, custom_servers: list[str] | None = None) -> bool:
    """True if `provider` is a known preference (including Automatic / valid Custom)."""
    if provider == AUTOMATIC or provider in PROVIDERS:
        return True
    if provider == CUSTOM:
        try:
            split_servers(custom_servers or [])
            return True
        except ValueError:
            return False
    return False


def plain_servers(provider: str, custom_servers: list[str]) -> tuple[list[str], list[str]]:
    if provider == AUTOMATIC:
        raise ValueError("automatic has no fixed plain servers; use candidate_order")
    if provider == CUSTOM:
        return split_servers(custom_servers)
    preset = PROVIDERS[provider]
    return list(preset.v4), list(preset.v6)


def doh_upstreams(provider: str) -> list[str]:
    """DoH URLs for dnsproxy; Automatic/Custom have none as a fixed set (use candidate_order)."""
    preset = PROVIDERS.get(provider)
    return list(preset.doh) if preset else []


def _encrypted_candidate(provider_id: str) -> Candidate:
    preset = PROVIDERS[provider_id]
    return Candidate(provider_id, ENCRYPTED, doh=preset.doh, v4=preset.v4, v6=preset.v6)


def _plain_candidate(provider_id: str, custom_servers: list[str] | None = None) -> Candidate:
    if provider_id == CUSTOM:
        v4, v6 = split_servers(custom_servers or [])
        return Candidate(CUSTOM, PLAIN, v4=tuple(v4), v6=tuple(v6))
    preset = PROVIDERS[provider_id]
    return Candidate(provider_id, PLAIN, v4=preset.v4, v6=preset.v6)


def candidate_order(mode: str, provider: str, custom_servers: list[str] | None = None) -> list[Candidate]:
    """Candidates to try, in order. Provider Automatic ≠ Mode Auto.

    - Automatic + Auto mode: encrypted CF→Google→Quad9, then plain CF→Google→Quad9.
    - Automatic + Encrypted: encrypted trio only.
    - Automatic + Plain: plain trio only.
    - Explicit preset: that provider's encrypted and/or plain steps per mode (never another brand).
    - Custom: plain only (empty list in Encrypted-only mode).
    """
    custom_servers = custom_servers or []
    want_encrypted = mode in ("auto", ENCRYPTED)
    want_plain = mode in ("auto", PLAIN)

    if provider == AUTOMATIC:
        out: list[Candidate] = []
        if want_encrypted:
            out.extend(_encrypted_candidate(pid) for pid in PRESET_ORDER)
        if want_plain:
            out.extend(_plain_candidate(pid) for pid in PRESET_ORDER)
        return out

    if provider == CUSTOM:
        return [_plain_candidate(CUSTOM, custom_servers)] if want_plain else []

    if provider not in PROVIDERS:
        raise ValueError(f"Unknown provider: {provider!r}")

    out = []
    if want_encrypted:
        out.append(_encrypted_candidate(provider))
    if want_plain:
        out.append(_plain_candidate(provider))
    return out


def candidate_label(candidate: Candidate) -> str:
    if candidate.provider_id == CUSTOM:
        name = "Custom"
    elif candidate.provider_id in PROVIDERS:
        name = PROVIDERS[candidate.provider_id].label
    else:
        name = candidate.provider_id
    kind = "Encrypted" if candidate.transport == ENCRYPTED else "Plain"
    return f"{name} {kind}"
