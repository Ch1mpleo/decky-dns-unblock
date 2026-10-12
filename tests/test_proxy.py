import unittest

from dns_unblock import providers, proxy


class ProxyArgsTests(unittest.TestCase):
    def test_build_args(self):
        args = proxy.build_args("/p/bin/dnsproxy", list(providers.PROVIDERS["cloudflare"].doh))
        self.assertEqual(args, [
            "/p/bin/dnsproxy", "-l", "127.0.0.2", "-p", "53",
            "-u", "https://1.1.1.1/dns-query", "-u", "https://1.0.0.1/dns-query",
            "--upstream-mode", "parallel", "--cache",
        ])

    def test_doh_upstreams(self):
        self.assertEqual(providers.doh_upstreams("quad9"),
                         ["https://9.9.9.9/dns-query", "https://149.112.112.112/dns-query"])
        self.assertEqual(providers.doh_upstreams(providers.CUSTOM), [])


if __name__ == "__main__":
    unittest.main()
