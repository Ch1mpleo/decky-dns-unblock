import unittest

from dns_unblock import dnsquery, health


def result(rcode="NOERROR", addresses=(), error=None):
    return dnsquery.Result(server="x", name="store.steampowered.com", rcode=rcode, addresses=list(addresses), error=error)


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


def row(network, doh, system, detail="NXDOMAIN"):
    v = lambda verdict: {"verdict": verdict, "detail": detail if verdict == health.BLOCKED else "1.2.3.4"}
    return {"domain": "store.steampowered.com", "network": v(network), "doh": v(doh), "system": v(system)}


class SummaryTests(unittest.TestCase):
    def test_blocked_network_fixed_by_deck(self):
        self.assertEqual(health.summarize([row(health.BLOCKED, health.OK, health.OK)]),
                         "Your network's DNS blocks Steam (NXDOMAIN). The Deck resolves Steam correctly.")

    def test_doh_blocked(self):
        text = health.summarize([row(health.OK, health.BLOCKED, health.OK, detail="timeout")])
        self.assertIn("doesn't block Steam", text)
        self.assertIn("Encrypted DNS can't get through on this network (timeout)", text)

    def test_unknown_network_not_mentioned(self):
        text = health.summarize([row(health.UNKNOWN, health.OK, health.BLOCKED)])
        self.assertEqual(text, "The Deck can't resolve Steam (NXDOMAIN).")


class DohUrlTests(unittest.TestCase):
    def test_rfc8484_get(self):
        url = dnsquery.doh_url("https://1.1.1.1/dns-query", "example.com")
        # ID 0, RD set, base64url without padding (RFC 8484 section 4.1).
        self.assertEqual(url, "https://1.1.1.1/dns-query?dns=AAABAAABAAAAAAAAB2V4YW1wbGUDY29tAAABAAE")


if __name__ == "__main__":
    unittest.main()
