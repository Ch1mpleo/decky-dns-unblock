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


if __name__ == "__main__":
    unittest.main()
