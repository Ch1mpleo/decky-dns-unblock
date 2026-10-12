import unittest

from dns_unblock import nm

# Captured on the Deck (SteamOS 3.8.28, NetworkManager 1.52.1), see docs/spike-notes.md.
DEVICES = "wlan0:wifi:connected\nlo:loopback:connected (externally)\np2p-dev-wlan0:wifi-p2p:disconnected\n"
DHCP = (
    "DHCP4.OPTION[1]:dhcp_client_identifier = 01:14:13:33:2f:b9:13\n"
    "DHCP4.OPTION[4]:domain_name_servers = 192.168.1.1 123.23.23.23\n"
    "DHCP4.OPTION[9]:requested_domain_name_servers = 1\n"
)
STATUS = """Link 3 (wlan0)
    Current Scopes: DNS LLMNR/IPv4 LLMNR/IPv6 mDNS/IPv4 mDNS/IPv6
         Protocols: +DefaultRoute +LLMNR +mDNS -DNSOverTLS DNSSEC=no/unsupported
Current DNS Server: 1.1.1.1
       DNS Servers: 127.0.0.2 1.1.1.1
"""


class ParserTests(unittest.TestCase):
    def test_devices(self):
        devices = nm.parse_devices(DEVICES)
        self.assertEqual(devices[0], ("wlan0", "wifi", "connected"))
        self.assertEqual(nm.pick_wifi_device(devices), "wlan0")

    def test_no_connected_wifi(self):
        self.assertIsNone(nm.pick_wifi_device(nm.parse_devices("wlan0:wifi:disconnected\n")))

    def test_terse_escaped_colon(self):
        self.assertEqual(nm.parse_devices(r"a\:b:wifi:connected"), [("a:b", "wifi", "connected")])

    def test_dhcp_dns_ignores_requested_option(self):
        self.assertEqual(nm.parse_dhcp_dns(DHCP), ["192.168.1.1", "123.23.23.23"])
        self.assertEqual(nm.parse_dhcp_dns("DHCP4.OPTION[9]:requested_domain_name_servers = 1\n"), [])

    def test_link_dns(self):
        self.assertEqual(nm.parse_link_dns("Link 3 (wlan0): 1.1.1.1 8.8.8.8\n"), ["1.1.1.1", "8.8.8.8"])
        self.assertEqual(nm.parse_link_dns("Link 3 (wlan0): 1.1.1.1#cloudflare-dns.com\n"), ["1.1.1.1"])
        self.assertEqual(nm.parse_link_dns("Link 3 (wlan0):\n"), [])

    def test_current_dns(self):
        self.assertEqual(nm.parse_current_dns(STATUS), "1.1.1.1")
        self.assertIsNone(nm.parse_current_dns("Link 3 (wlan0)\n"))


if __name__ == "__main__":
    unittest.main()
