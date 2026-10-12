"""Block detection and diagnostics. The classifier is pure so it can be unit-tested."""

import asyncio
import ipaddress

from . import dnsquery

STEAM_DOMAINS = (
    "store.steampowered.com",
    "steamcommunity.com",
    "api.steampowered.com",
    "login.steampowered.com",
)
SYSTEM_RESOLVER = "127.0.0.53"

OK = "ok"
BLOCKED = "blocked"
UNKNOWN = "unknown"


def classify(result: dnsquery.Result | None) -> tuple[str, str]:
    """Return (verdict, short detail) for one lookup.

    Blocked: NXDOMAIN/SERVFAIL/REFUSED, timeout, no answer, or a sinkhole address (0.0.0.0, loopback, private).
    Different public IPs than another resolver are normal (CDNs), so they count as OK.
    """
    if result is None:
        return UNKNOWN, "no server"
    if result.error:
        return BLOCKED, result.error
    if result.rcode != "NOERROR":
        return BLOCKED, result.rcode or "no answer"
    if not result.addresses:
        return BLOCKED, "empty answer"
    for address in result.addresses:
        ip = ipaddress.ip_address(address)
        if ip.is_unspecified or ip.is_loopback or ip.is_private or ip.is_link_local:
            return BLOCKED, f"sinkhole {address}"
    return OK, result.addresses[0]


async def diagnose(network_dns: list[str], timeout: float = 3.0) -> list[dict]:
    """For each Steam domain, compare the network's own DNS with what the Deck resolves right now."""
    async def lookup(server: str | None, domain: str) -> dict:
        result = await dnsquery.aquery(server, domain, timeout=timeout) if server else None
        verdict, detail = classify(result)
        return {"verdict": verdict, "detail": detail}

    network_server = network_dns[0] if network_dns else None
    rows = await asyncio.gather(*(
        asyncio.gather(lookup(network_server, d), lookup(SYSTEM_RESOLVER, d)) for d in STEAM_DOMAINS
    ))
    return [
        {"domain": domain, "network": network, "system": system}
        for domain, (network, system) in zip(STEAM_DOMAINS, rows)
    ]
