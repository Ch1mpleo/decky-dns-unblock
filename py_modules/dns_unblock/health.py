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
# Reference for "does encrypted DNS work from this network". Fixed rather than the chosen provider because
# urllib only speaks HTTP/1.1 and Quad9's DoH on port 443 requires HTTP/2.
REFERENCE_DOH = "https://1.1.1.1/dns-query"

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


async def verify(server: str, timeout: float = 3.0, attempts: int = 1) -> tuple[bool, str]:
    """Check that `server` resolves a Steam domain correctly. Only "connection refused" is retried (a proxy that
    was just started may still be binding its port); timeouts and blocked answers fail straight away."""
    detail = ""
    for attempt in range(attempts):
        if attempt:
            await asyncio.sleep(0.3)
        result = await dnsquery.aquery(server, STEAM_DOMAINS[0], timeout=timeout)
        verdict, detail = classify(result)
        if verdict == OK:
            return True, detail
        if "refused" not in (result.error or "").lower():
            break
    return False, detail


async def diagnose(network_dns: list[str], timeout: float = 3.0) -> list[dict]:
    """For each Steam domain, compare the network's own DNS, encrypted DNS (DoH) and what the Deck resolves now."""
    def verdict(result: dnsquery.Result | None) -> dict:
        v, detail = classify(result)
        return {"verdict": v, "detail": detail}

    async def plain(server: str | None, domain: str) -> dict:
        return verdict(await dnsquery.aquery(server, domain, timeout=timeout) if server else None)

    async def doh(domain: str) -> dict:
        return verdict(await dnsquery.adoh_query(REFERENCE_DOH, domain, timeout=timeout + 1))

    network_server = network_dns[0] if network_dns else None
    rows = await asyncio.gather(*(
        asyncio.gather(plain(network_server, d), doh(d), plain(SYSTEM_RESOLVER, d)) for d in STEAM_DOMAINS
    ))
    return [
        {"domain": domain, "network": network, "doh": doh_result, "system": system}
        for domain, (network, doh_result, system) in zip(STEAM_DOMAINS, rows)
    ]


def summarize(rows: list[dict]) -> str:
    """One or two plain sentences explaining the diagnostics table."""
    def first_blocked(column: str) -> str | None:
        return next((r[column]["detail"] for r in rows if r[column]["verdict"] == BLOCKED), None)

    parts = []
    network = first_blocked("network")
    if network:
        parts.append(f"Your network's DNS blocks Steam ({network}).")
    elif all(r["network"]["verdict"] == OK for r in rows):
        parts.append("Your network's DNS doesn't block Steam.")
    doh = first_blocked("doh")
    if doh:
        parts.append(f"Encrypted DNS can't get through on this network ({doh}).")
    system = first_blocked("system")
    parts.append(f"The Deck can't resolve Steam ({system})." if system else "The Deck resolves Steam correctly.")
    return " ".join(parts)
