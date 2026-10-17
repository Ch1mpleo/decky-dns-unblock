"""Block detection, DNS/HTTPS probes, and diagnostics. Pure classifiers are unit-tested."""

from __future__ import annotations

import asyncio
import ipaddress
from dataclasses import dataclass, field

from . import dnsquery, httpscheck

STEAM_DOMAINS = (
    "store.steampowered.com",
    "steamcommunity.com",
    "api.steampowered.com",
    "login.steampowered.com",
)
# Domains used for provider selection / apply verification.
PROBE_DOMAINS = (
    "store.steampowered.com",
    "steamcommunity.com",
)
SYSTEM_RESOLVER = "127.0.0.53"

DNS_TIMEOUT = 3.0
HTTPS_TIMEOUT = httpscheck.HTTPS_TIMEOUT
PROVIDER_TIMEOUT = 10.0

OK = "ok"
BLOCKED = "blocked"
UNKNOWN = "unknown"

# Finer DNS outcomes for selection / status (blocking ≠ timeout).
RESOLVED = "resolved"
LOOKUP_FAILED = "lookup_failed"
POSSIBLE_DNS_BLOCKING = "possible_dns_blocking"


@dataclass
class DomainDns:
    domain: str
    outcome: str
    detail: str
    addresses: list[str] = field(default_factory=list)


@dataclass
class DnsProbe:
    ok: bool
    detail: str
    domains: list[DomainDns] = field(default_factory=list)

    @property
    def addresses_by_domain(self) -> dict[str, list[str]]:
        return {d.domain: list(d.addresses) for d in self.domains if d.addresses}


@dataclass
class HttpsProbe:
    ok: bool
    detail: str
    results: list[httpscheck.HttpsResult] = field(default_factory=list)


@dataclass
class Evaluation:
    """Result of probing a resolver: DNS required; HTTPS optional success."""

    dns_ok: bool
    https_ok: bool
    detail: str
    dns: DnsProbe | None = None
    https: HttpsProbe | None = None

    @property
    def verified(self) -> bool:
        return self.dns_ok and self.https_ok

    @property
    def dns_only(self) -> bool:
        return self.dns_ok and not self.https_ok


def classify(result: dnsquery.Result | None) -> tuple[str, str]:
    """Return (verdict, short detail) for one lookup (diagnostics table).

    Blocked: NXDOMAIN/SERVFAIL/REFUSED, timeout, no answer, or a sinkhole address (0.0.0.0, loopback, private).
    Different public IPs than another resolver are normal (CDNs), so they count as OK.
    """
    outcome, detail, _ = _inspect(result)
    if outcome == RESOLVED:
        return OK, detail
    if outcome == UNKNOWN:
        return UNKNOWN, detail
    return BLOCKED, detail


def dns_outcome(result: dnsquery.Result | None) -> tuple[str, str]:
    """Return (resolved|lookup_failed|possible_dns_blocking|unknown, detail)."""
    outcome, detail, _ = _inspect(result)
    return outcome, detail


def _inspect(result: dnsquery.Result | None) -> tuple[str, str, list[str]]:
    if result is None:
        return UNKNOWN, "no server", []
    if result.error:
        err = result.error.lower()
        # Timeouts / refused / network errors are reachability, not proven ISP lying.
        if any(token in err for token in ("timeout", "refused", "unreachable", "network is unreachable")):
            return LOOKUP_FAILED, result.error, []
        return LOOKUP_FAILED, result.error, []
    if result.rcode != "NOERROR":
        rcode = result.rcode or "no answer"
        if rcode in ("NXDOMAIN", "SERVFAIL", "REFUSED"):
            return POSSIBLE_DNS_BLOCKING, rcode, []
        return LOOKUP_FAILED, rcode, []
    if not result.addresses:
        return POSSIBLE_DNS_BLOCKING, "empty answer", []
    usable: list[str] = []
    for address in result.addresses:
        ip = ipaddress.ip_address(address)
        if ip.is_unspecified or ip.is_loopback or ip.is_private or ip.is_link_local:
            return POSSIBLE_DNS_BLOCKING, f"sinkhole {address}", []
        usable.append(address)
    return RESOLVED, usable[0], usable


def _usable_addresses(result: dnsquery.Result) -> list[str]:
    outcome, _, addresses = _inspect(result)
    return addresses if outcome == RESOLVED else []


async def resolve_domain(
    server: str,
    domain: str,
    timeout: float = DNS_TIMEOUT,
    port: int = 53,
) -> DomainDns:
    """Resolve A and AAAA. Missing AAAA alone is not failure if A is usable (and vice versa)."""
    a_res, aaaa_res = await asyncio.gather(
        dnsquery.aquery(server, domain, qtype=dnsquery.TYPE_A, timeout=timeout, port=port),
        dnsquery.aquery(server, domain, qtype=dnsquery.TYPE_AAAA, timeout=timeout, port=port),
    )
    v4 = _usable_addresses(a_res)
    v6 = _usable_addresses(aaaa_res)
    if v4 or v6:
        return DomainDns(domain, RESOLVED, (v4 or v6)[0], v4 + v6)

    # Prefer reporting blocking evidence over a bare timeout when either family shows it.
    for res in (a_res, aaaa_res):
        outcome, detail = dns_outcome(res)
        if outcome == POSSIBLE_DNS_BLOCKING:
            return DomainDns(domain, outcome, detail)
    for res in (a_res, aaaa_res):
        outcome, detail = dns_outcome(res)
        if outcome != UNKNOWN:
            return DomainDns(domain, outcome, detail)
    return DomainDns(domain, LOOKUP_FAILED, "no answer")


async def probe_dns(
    server: str,
    domains: tuple[str, ...] = PROBE_DOMAINS,
    timeout: float = DNS_TIMEOUT,
    port: int = 53,
    attempts: int = 1,
) -> DnsProbe:
    """Concurrent dual-domain DNS check. Retries only on connection refused (proxy still binding)."""
    detail = ""
    last: DnsProbe | None = None
    for attempt in range(max(attempts, 1)):
        if attempt:
            await asyncio.sleep(0.3)
        rows = list(await asyncio.gather(*(
            resolve_domain(server, domain, timeout=timeout, port=port) for domain in domains
        )))
        last = DnsProbe(all(r.outcome == RESOLVED for r in rows), "", rows)
        if last.ok:
            last.detail = rows[0].detail
            return last
        detail = "; ".join(f"{r.domain}: {r.detail}" for r in rows if r.outcome != RESOLVED)
        last.detail = detail
        refused = any("refused" in (r.detail or "").lower() for r in rows)
        if not refused:
            break
    assert last is not None
    return last


async def probe_https(
    addresses_by_domain: dict[str, list[str]],
    timeout: float = HTTPS_TIMEOUT,
) -> HttpsProbe:
    """Concurrent HTTPS checks; 2xx/3xx = reachable. HTTP 4xx/5xx reported separately from connect failure."""
    domains = list(addresses_by_domain.keys())
    results = list(await asyncio.gather(*(
        httpscheck.check_hostname(domain, addresses_by_domain.get(domain, []), timeout=timeout)
        for domain in domains
    )))
    if all(r.ok for r in results):
        return HttpsProbe(True, results[0].detail if results else "ok", results)
    failed = [r for r in results if not r.ok]
    detail = "; ".join(f"{r.hostname}: {r.detail}" for r in failed)
    return HttpsProbe(False, detail, results)


async def evaluate_resolver(
    server: str,
    port: int = 53,
    domains: tuple[str, ...] = PROBE_DOMAINS,
    dns_timeout: float = DNS_TIMEOUT,
    https_timeout: float = HTTPS_TIMEOUT,
    overall_timeout: float = PROVIDER_TIMEOUT,
    attempts: int = 1,
    require_https: bool = True,
) -> Evaluation:
    """DNS (+ optional HTTPS) against a resolver, capped by overall_timeout."""
    async def run() -> Evaluation:
        dns = await probe_dns(server, domains=domains, timeout=dns_timeout, port=port, attempts=attempts)
        if not dns.ok:
            return Evaluation(False, False, dns.detail, dns=dns)
        if not require_https:
            return Evaluation(True, False, dns.detail, dns=dns)
        https = await probe_https(dns.addresses_by_domain, timeout=https_timeout)
        if https.ok:
            return Evaluation(True, True, https.detail, dns=dns, https=https)
        return Evaluation(True, False, https.detail, dns=dns, https=https)

    try:
        return await asyncio.wait_for(run(), timeout=overall_timeout)
    except asyncio.TimeoutError:
        return Evaluation(False, False, "provider evaluation timed out")


async def verify_plain_servers(
    v4: list[str],
    v6: list[str],
    domains: tuple[str, ...] = PROBE_DOMAINS,
    timeout: float = DNS_TIMEOUT,
) -> tuple[list[str], list[str], str]:
    """Test each plain server independently; return only those that resolve both probe domains."""
    verified_v4: list[str] = []
    verified_v6: list[str] = []
    failures: list[str] = []

    async def check(server: str) -> tuple[str, bool, str]:
        probe = await probe_dns(server, domains=domains, timeout=timeout)
        return server, probe.ok, probe.detail

    results = await asyncio.gather(*(check(s) for s in list(v4) + list(v6)))
    v4_set = set(v4)
    for server, ok, detail in results:
        if ok:
            (verified_v4 if server in v4_set else verified_v6).append(server)
        else:
            failures.append(f"{server}: {detail}")

    if verified_v4 or verified_v6:
        return verified_v4, verified_v6, (verified_v4 or verified_v6)[0]
    return [], [], "; ".join(failures) or "No usable plain DNS"


async def verify(server: str, timeout: float = DNS_TIMEOUT, attempts: int = 1, port: int = 53) -> tuple[bool, str]:
    """Check that `server` resolves the probe Steam domains (A/AAAA). Used by apply path."""
    probe = await probe_dns(server, timeout=timeout, port=port, attempts=attempts)
    return probe.ok, probe.detail


def _dns_cell(domain_dns: DomainDns | None) -> dict:
    if domain_dns is None:
        return {"verdict": UNKNOWN, "detail": "no server", "addresses": []}
    return {
        "verdict": domain_dns.outcome,
        "detail": domain_dns.detail,
        "addresses": list(domain_dns.addresses),
    }


def _https_cell(result: httpscheck.HttpsResult | None) -> dict:
    if result is None:
        return {"verdict": UNKNOWN, "detail": "skipped", "status_code": None}
    return {
        "verdict": result.outcome,
        "detail": result.detail,
        "status_code": result.status_code,
    }


async def diagnose(
    network_dns: list[str],
    provider_server: str | None,
    provider_port: int = 53,
    domains: tuple[str, ...] = PROBE_DOMAINS,
    timeout: float = DNS_TIMEOUT,
    https_timeout: float = HTTPS_TIMEOUT,
) -> list[dict]:
    """Per-domain Network / Provider / Deck DNS cells plus HTTPS against provider-resolved addresses.

    Provider is whatever the plugin chose to test (live dnsproxy, plain server, or temporary probe) —
    not a fixed Cloudflare DoH URL.
    """
    network_server = network_dns[0] if network_dns else None

    async def missing(domain: str) -> DomainDns:
        return DomainDns(domain, UNKNOWN, "no server")

    async def one_domain(domain: str) -> dict:
        network_row, provider_row, system_row = await asyncio.gather(
            resolve_domain(network_server, domain, timeout=timeout) if network_server else missing(domain),
            resolve_domain(provider_server, domain, timeout=timeout, port=provider_port)
            if provider_server else missing(domain),
            resolve_domain(SYSTEM_RESOLVER, domain, timeout=timeout),
        )
        # Prefer provider-resolved addresses for HTTPS so we do not use system DNS.
        addresses = provider_row.addresses or system_row.addresses
        https_result = None
        if addresses:
            https_result = await httpscheck.check_hostname(domain, addresses, timeout=https_timeout)
        return {
            "domain": domain,
            "network": _dns_cell(network_row),
            "provider": _dns_cell(provider_row),
            "system": _dns_cell(system_row),
            "https": _https_cell(https_result),
        }

    return list(await asyncio.gather(*(one_domain(d) for d in domains)))


def summarize(rows: list[dict], resolver_label: str = "provider") -> str:
    """Plain-language summary; blocking is comparative, not a synonym for timeout."""
    if not rows:
        return "No diagnostic results."

    def first(column: str, verdict: str) -> str | None:
        return next((r[column]["detail"] for r in rows if r[column]["verdict"] == verdict), None)

    parts: list[str] = []

    if first("network", POSSIBLE_DNS_BLOCKING):
        detail = first("network", POSSIBLE_DNS_BLOCKING)
        parts.append(f"Possible DNS blocking on the network resolver ({detail}).")
    elif first("network", LOOKUP_FAILED):
        parts.append(f"Network DNS lookup failed ({first('network', LOOKUP_FAILED)}).")
    elif all(r["network"]["verdict"] == RESOLVED for r in rows):
        parts.append("Network DNS resolved Steam.")
    elif all(r["network"]["verdict"] == UNKNOWN for r in rows):
        pass
    else:
        parts.append("Network DNS did not fully resolve Steam.")

    if first("provider", POSSIBLE_DNS_BLOCKING):
        parts.append(f"{resolver_label} shows possible DNS blocking ({first('provider', POSSIBLE_DNS_BLOCKING)}).")
    elif first("provider", LOOKUP_FAILED):
        parts.append(f"{resolver_label} lookup failed ({first('provider', LOOKUP_FAILED)}).")
    elif all(r["provider"]["verdict"] == RESOLVED for r in rows):
        parts.append(f"{resolver_label}: DNS resolved.")
    elif all(r["provider"]["verdict"] == UNKNOWN for r in rows):
        parts.append(f"{resolver_label}: not tested.")
    else:
        parts.append(f"{resolver_label}: DNS incomplete.")

    if all(r["https"]["verdict"] == httpscheck.REACHABLE for r in rows):
        parts.append("HTTPS reachable for Steam endpoints.")
    elif any(r["https"]["verdict"] == httpscheck.HTTP_ERROR for r in rows):
        detail = first("https", httpscheck.HTTP_ERROR) or "HTTP error"
        parts.append(f"Steam HTTPS returned an HTTP error ({detail}); not inferred as ISP DNS blocking.")
    elif any(r["https"]["verdict"] == httpscheck.CONNECTION_FAILED for r in rows):
        parts.append("Steam access unverified (HTTPS connection failed).")
    elif all(r["provider"]["verdict"] == RESOLVED for r in rows):
        parts.append("Steam access unverified.")

    if first("system", POSSIBLE_DNS_BLOCKING) or first("system", LOOKUP_FAILED):
        detail = first("system", POSSIBLE_DNS_BLOCKING) or first("system", LOOKUP_FAILED)
        parts.append(f"Deck resolver issue ({detail}).")
    elif all(r["system"]["verdict"] == RESOLVED for r in rows):
        parts.append("Deck resolver OK.")

    return " ".join(parts) if parts else "Diagnostics complete."


# Backward-compatible alias used by older tests / call sites that only need the network-block story.
def summarize_legacy(rows: list[dict]) -> str:
    """Summarize rows that still use ok/blocked/unknown + doh column (unit tests / migration)."""
    def first_blocked(column: str) -> str | None:
        return next((r[column]["detail"] for r in rows if r[column]["verdict"] == BLOCKED), None)

    parts = []
    network = first_blocked("network")
    if network:
        parts.append(f"Your network's DNS blocks Steam ({network}).")
    elif all(r["network"]["verdict"] == OK for r in rows):
        parts.append("Your network's DNS doesn't block Steam.")
    doh = first_blocked("doh") if rows and "doh" in rows[0] else None
    if doh:
        parts.append(f"Encrypted DNS can't get through on this network ({doh}).")
    system = first_blocked("system")
    parts.append(f"The Deck can't resolve Steam ({system})." if system else "The Deck resolves Steam correctly.")
    return " ".join(parts)
