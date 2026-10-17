import socket
import unittest
from unittest.mock import MagicMock, patch

from dns_unblock import httpscheck


class HttpsResultTests(unittest.TestCase):
    def test_ok_flag(self):
        self.assertTrue(httpscheck.HttpsResult("h", "1.2.3.4", httpscheck.REACHABLE, "HTTP 200", 200).ok)
        self.assertFalse(httpscheck.HttpsResult("h", "1.2.3.4", httpscheck.HTTP_ERROR, "HTTP 503", 503).ok)
        self.assertFalse(httpscheck.HttpsResult("h", "1.2.3.4", httpscheck.CONNECTION_FAILED, "timeout").ok)


class HttpsGetTests(unittest.TestCase):
    def test_bad_address(self):
        result = httpscheck.https_get("example.com", "not-an-ip", timeout=1)
        self.assertEqual(result.outcome, httpscheck.CONNECTION_FAILED)
        self.assertIn("bad address", result.detail)

    def test_connection_failure(self):
        result = httpscheck.https_get("localhost", "127.0.0.1", timeout=0.3)
        self.assertEqual(result.outcome, httpscheck.CONNECTION_FAILED)

    def _mock_tls(self, response: bytes):
        tls = MagicMock()
        tls.recv.side_effect = [response, b""]
        wrap = MagicMock()
        wrap.__enter__.return_value = tls
        wrap.__exit__.return_value = False
        sock = MagicMock()
        sock.__enter__.return_value = sock
        sock.__exit__.return_value = False
        return sock, wrap, tls

    def test_reachable_2xx_with_sni_and_host(self):
        sock, wrap, tls = self._mock_tls(b"HTTP/1.1 302 Found\r\nContent-Length: 0\r\n\r\n")
        with patch("dns_unblock.httpscheck.socket.socket", return_value=sock), \
             patch("dns_unblock.httpscheck._ssl_context") as ctx:
            ctx.return_value.wrap_socket.return_value = wrap
            result = httpscheck.https_get("store.steampowered.com", "23.1.2.3", timeout=1)

        self.assertEqual(result.outcome, httpscheck.REACHABLE)
        self.assertEqual(result.status_code, 302)
        sock.connect.assert_called_once_with(("23.1.2.3", 443))
        ctx.return_value.wrap_socket.assert_called_once()
        self.assertEqual(ctx.return_value.wrap_socket.call_args.kwargs["server_hostname"], "store.steampowered.com")
        sent = tls.sendall.call_args.args[0].decode()
        self.assertIn("Host: store.steampowered.com", sent)
        self.assertIn("GET / HTTP/1.1", sent)

    def test_http_5xx(self):
        sock, wrap, _tls = self._mock_tls(b"HTTP/1.1 503 Service Unavailable\r\n\r\n")
        with patch("dns_unblock.httpscheck.socket.socket", return_value=sock), \
             patch("dns_unblock.httpscheck._ssl_context") as ctx:
            ctx.return_value.wrap_socket.return_value = wrap
            result = httpscheck.https_get("steamcommunity.com", "8.8.8.8", timeout=1)
        self.assertEqual(result.outcome, httpscheck.HTTP_ERROR)
        self.assertEqual(result.status_code, 503)

    def test_timeout(self):
        sock = MagicMock()
        sock.__enter__.return_value = sock
        sock.__exit__.return_value = False
        sock.connect.side_effect = socket.timeout
        with patch("dns_unblock.httpscheck.socket.socket", return_value=sock):
            result = httpscheck.https_get("store.steampowered.com", "1.1.1.1", timeout=1)
        self.assertEqual(result.outcome, httpscheck.CONNECTION_FAILED)
        self.assertEqual(result.detail, "timeout")


class CheckHostnameTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_addresses(self):
        result = await httpscheck.check_hostname("store.steampowered.com", [])
        self.assertEqual(result.outcome, httpscheck.CONNECTION_FAILED)

    async def test_tries_ipv4_before_ipv6_and_stops_on_reachable(self):
        calls: list[str] = []

        async def fake(hostname, address, timeout=5.0, path="/"):
            calls.append(address)
            if address.startswith("2001:"):
                return httpscheck.HttpsResult(hostname, address, httpscheck.CONNECTION_FAILED, "fail")
            return httpscheck.HttpsResult(hostname, address, httpscheck.REACHABLE, "HTTP 200", 200)

        with patch("dns_unblock.httpscheck.ahttps_get", side_effect=fake):
            result = await httpscheck.check_hostname(
                "store.steampowered.com",
                ["2001:db8::1", "23.1.2.3"],
            )
        self.assertTrue(result.ok)
        self.assertEqual(calls, ["23.1.2.3"])  # IPv4 preferred; stop on success

    async def test_stops_on_http_error(self):
        async def fake(hostname, address, timeout=5.0, path="/"):
            return httpscheck.HttpsResult(hostname, address, httpscheck.HTTP_ERROR, "HTTP 403", 403)

        with patch("dns_unblock.httpscheck.ahttps_get", side_effect=fake):
            result = await httpscheck.check_hostname("x", ["1.1.1.1", "1.0.0.1"])
        self.assertEqual(result.outcome, httpscheck.HTTP_ERROR)


if __name__ == "__main__":
    unittest.main()
