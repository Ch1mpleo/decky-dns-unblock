import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from dns_unblock import dnsquery, health, httpscheck


def result(rcode="NOERROR", addresses=(), error=None, name="store.steampowered.com"):
    return dnsquery.Result(server="x", name=name, rcode=rcode, addresses=list(addresses), error=error)


class ClassifyTests(unittest.TestCase):
    def test_ok(self):
        self.assertEqual(health.classify(result(addresses=["23.15.142.182"])), (health.OK, "23.15.142.182"))

    def test_isp_nxdomain(self):
        self.assertEqual(health.classify(result(rcode="NXDOMAIN")), (health.BLOCKED, "NXDOMAIN"))

    def test_timeout_and_empty(self):
        self.assertEqual(health.classify(result(rcode=None, error="timeout"))[0], health.BLOCKED)
        self.assertEqual(health.classify(result())[0], health.BLOCKED)

    def test_sinkholes(self):
        for address in ("0.0.0.0", "127.0.0.1", "10.10.34.35", "192.168.1.1", "::"):
            self.assertEqual(health.classify(result(addresses=[address]))[0], health.BLOCKED, address)

    def test_no_server(self):
        self.assertEqual(health.classify(None)[0], health.UNKNOWN)


class DnsOutcomeTests(unittest.TestCase):
    def test_resolved_vs_blocking_vs_lookup(self):
        self.assertEqual(health.dns_outcome(result(addresses=["23.15.142.182"]))[0], health.RESOLVED)
        self.assertEqual(health.dns_outcome(result(rcode="NXDOMAIN"))[0], health.POSSIBLE_DNS_BLOCKING)
        self.assertEqual(health.dns_outcome(result(rcode="SERVFAIL"))[0], health.POSSIBLE_DNS_BLOCKING)
        self.assertEqual(health.dns_outcome(result(error="timeout"))[0], health.LOOKUP_FAILED)
        self.assertEqual(health.dns_outcome(result(error="Connection refused"))[0], health.LOOKUP_FAILED)


def legacy_row(network, doh, system, detail="NXDOMAIN"):
    v = lambda verdict: {"verdict": verdict, "detail": detail if verdict == health.BLOCKED else "1.2.3.4"}
    return {"domain": "store.steampowered.com", "network": v(network), "doh": v(doh), "system": v(system)}


def diag_row(network, provider, system, https, detail="NXDOMAIN"):
    cell = lambda verdict, d=detail: {"verdict": verdict, "detail": d if verdict != health.RESOLVED else "1.2.3.4", "addresses": []}
    return {
        "domain": "store.steampowered.com",
        "network": cell(network),
        "provider": cell(provider),
        "system": cell(system),
        "https": {"verdict": https, "detail": detail, "status_code": None},
    }


class SummaryTests(unittest.TestCase):
    def test_legacy_blocked_network_fixed_by_deck(self):
        self.assertEqual(
            health.summarize_legacy([legacy_row(health.BLOCKED, health.OK, health.OK)]),
            "Your network's DNS blocks Steam (NXDOMAIN). The Deck resolves Steam correctly.",
        )

    def test_possible_blocking_vs_lookup_failed(self):
        text = health.summarize([diag_row(
            health.POSSIBLE_DNS_BLOCKING, health.RESOLVED, health.RESOLVED, "reachable", "NXDOMAIN"
        )])
        self.assertIn("Possible DNS blocking", text)
        self.assertIn("DNS resolved", text)
        self.assertIn("HTTPS reachable", text)

    def test_https_unverified(self):
        text = health.summarize([diag_row(
            health.RESOLVED, health.RESOLVED, health.RESOLVED, "connection_failed", "timeout"
        )])
        self.assertIn("Steam access unverified", text)
        self.assertNotIn("Possible DNS blocking", text)

    def test_http_error_not_called_blocking(self):
        text = health.summarize([diag_row(
            health.RESOLVED, health.RESOLVED, health.RESOLVED, "http_error", "HTTP 503"
        )])
        self.assertIn("HTTP error", text)
        self.assertIn("not inferred as ISP DNS blocking", text)


class DohUrlTests(unittest.TestCase):
    def test_rfc8484_get(self):
        url = dnsquery.doh_url("https://1.1.1.1/dns-query", "example.com")
        # ID 0, RD set, base64url without padding (RFC 8484 section 4.1).
        self.assertEqual(url, "https://1.1.1.1/dns-query?dns=AAABAAABAAAAAAAAB2V4YW1wbGUDY29tAAABAAE")


class ResolveDomainTests(unittest.IsolatedAsyncioTestCase):
    async def test_aaaa_missing_alone_is_ok(self):
        async def fake_query(server, name, qtype=dnsquery.TYPE_A, timeout=3.0, port=53):
            if qtype == dnsquery.TYPE_A:
                return result(addresses=["23.15.142.182"], name=name)
            return result(rcode="NOERROR", addresses=(), name=name)  # empty AAAA

        with patch("dns_unblock.dnsquery.aquery", side_effect=fake_query):
            row = await health.resolve_domain("1.1.1.1", "store.steampowered.com")
        self.assertEqual(row.outcome, health.RESOLVED)
        self.assertEqual(row.addresses, ["23.15.142.182"])

    async def test_a_missing_aaaa_ok(self):
        async def fake_query(server, name, qtype=dnsquery.TYPE_A, timeout=3.0, port=53):
            if qtype == dnsquery.TYPE_AAAA:
                return result(addresses=["2606:4700:4700::1111"], name=name)
            return result(rcode="NXDOMAIN", name=name)

        with patch("dns_unblock.dnsquery.aquery", side_effect=fake_query):
            row = await health.resolve_domain("1.1.1.1", "steamcommunity.com")
        self.assertEqual(row.outcome, health.RESOLVED)
        self.assertEqual(row.addresses, ["2606:4700:4700::1111"])

    async def test_nxdomain_both(self):
        async def fake_query(server, name, qtype=dnsquery.TYPE_A, timeout=3.0, port=53):
            return result(rcode="NXDOMAIN", name=name)

        with patch("dns_unblock.dnsquery.aquery", side_effect=fake_query):
            row = await health.resolve_domain("192.168.1.1", "store.steampowered.com")
        self.assertEqual(row.outcome, health.POSSIBLE_DNS_BLOCKING)


class ProbeDnsTests(unittest.IsolatedAsyncioTestCase):
    async def test_both_domains_required(self):
        async def fake_resolve(server, domain, timeout=3.0, port=53):
            if domain.startswith("store"):
                return health.DomainDns(domain, health.RESOLVED, "1.2.3.4", ["1.2.3.4"])
            return health.DomainDns(domain, health.POSSIBLE_DNS_BLOCKING, "NXDOMAIN")

        with patch("dns_unblock.health.resolve_domain", side_effect=fake_resolve):
            probe = await health.probe_dns("1.1.1.1")
        self.assertFalse(probe.ok)
        self.assertIn("steamcommunity.com", probe.detail)

    async def test_success(self):
        async def fake_resolve(server, domain, timeout=3.0, port=53):
            return health.DomainDns(domain, health.RESOLVED, "9.9.9.9", ["9.9.9.9"])

        with patch("dns_unblock.health.resolve_domain", side_effect=fake_resolve):
            probe = await health.probe_dns("9.9.9.9")
        self.assertTrue(probe.ok)


class VerifyPlainServersTests(unittest.IsolatedAsyncioTestCase):
    async def test_secondary_succeeds_when_primary_fails(self):
        async def fake_probe(server, domains=health.PROBE_DOMAINS, timeout=3.0, port=53, attempts=1):
            ok = server == "1.0.0.1"
            return health.DnsProbe(ok, "ok" if ok else "timeout", [])

        with patch("dns_unblock.health.probe_dns", side_effect=fake_probe):
            v4, v6, detail = await health.verify_plain_servers(["1.1.1.1", "1.0.0.1"], ["2606:4700:4700::1111"])
        self.assertEqual(v4, ["1.0.0.1"])
        self.assertEqual(v6, [])
        self.assertEqual(detail, "1.0.0.1")

    async def test_ipv6_only_when_reachable(self):
        async def fake_probe(server, domains=health.PROBE_DOMAINS, timeout=3.0, port=53, attempts=1):
            ok = ":" in server
            return health.DnsProbe(ok, "ok" if ok else "fail", [])

        with patch("dns_unblock.health.probe_dns", side_effect=fake_probe):
            v4, v6, _ = await health.verify_plain_servers(["1.1.1.1"], ["2606:4700:4700::1111"])
        self.assertEqual(v4, [])
        self.assertEqual(v6, ["2606:4700:4700::1111"])


class EvaluateResolverTests(unittest.IsolatedAsyncioTestCase):
    async def test_dns_ok_https_fail_is_dns_only(self):
        dns = health.DnsProbe(True, "1.2.3.4", [
            health.DomainDns("store.steampowered.com", health.RESOLVED, "1.2.3.4", ["1.2.3.4"]),
            health.DomainDns("steamcommunity.com", health.RESOLVED, "1.2.3.5", ["1.2.3.5"]),
        ])
        https = health.HttpsProbe(False, "timeout", [])
        with patch("dns_unblock.health.probe_dns", AsyncMock(return_value=dns)), \
             patch("dns_unblock.health.probe_https", AsyncMock(return_value=https)):
            evaluation = await health.evaluate_resolver("1.1.1.1")
        self.assertTrue(evaluation.dns_ok)
        self.assertFalse(evaluation.https_ok)
        self.assertTrue(evaluation.dns_only)

    async def test_overall_timeout(self):
        async def slow(*_a, **_k):
            await asyncio.sleep(10)
            return health.DnsProbe(True, "x", [])

        with patch("dns_unblock.health.probe_dns", side_effect=slow):
            evaluation = await health.evaluate_resolver("1.1.1.1", overall_timeout=0.05)
        self.assertFalse(evaluation.dns_ok)
        self.assertIn("timed out", evaluation.detail)


class ProbeHttpsTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_domains(self):
        async def fake(hostname, addresses, timeout=5.0):
            return httpscheck.HttpsResult(hostname, addresses[0], httpscheck.REACHABLE, "HTTP 200", 200)

        with patch("dns_unblock.httpscheck.check_hostname", side_effect=fake):
            probe = await health.probe_https({
                "store.steampowered.com": ["1.1.1.1"],
                "steamcommunity.com": ["1.0.0.1"],
            })
        self.assertTrue(probe.ok)


if __name__ == "__main__":
    unittest.main()
