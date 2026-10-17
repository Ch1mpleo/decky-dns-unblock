import logging
import unittest
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

from dns_unblock import providers, proxy


class ProxyArgsTests(unittest.TestCase):
    def test_build_args_live(self):
        args = proxy.build_args("/p/bin/dnsproxy", list(providers.PROVIDERS["cloudflare"].doh))
        self.assertEqual(args, [
            "/p/bin/dnsproxy", "-l", "127.0.0.2", "-p", "53",
            "-u", "https://1.1.1.1/dns-query", "-u", "https://1.0.0.1/dns-query",
            "--upstream-mode", "parallel", "--cache",
        ])

    def test_build_args_probe_port_no_cache(self):
        args = proxy.build_args("/p/bin/dnsproxy", ["https://8.8.8.8/dns-query"], listen="127.0.0.2", port=15353, cache=False)
        self.assertEqual(args[:6], ["/p/bin/dnsproxy", "-l", "127.0.0.2", "-p", "15353", "-u"])
        self.assertNotIn("--cache", args)
        self.assertIn("--upstream-mode", args)

    def test_doh_upstreams(self):
        self.assertEqual(providers.doh_upstreams("quad9"),
                         ["https://9.9.9.9/dns-query", "https://149.112.112.112/dns-query"])
        self.assertEqual(providers.doh_upstreams(providers.CUSTOM), [])

    def test_probe_ports(self):
        self.assertEqual(proxy.PROBE_PORTS, (15353, 15354, 15355))


class ProbeProxyTests(unittest.IsolatedAsyncioTestCase):
    async def test_tries_next_port_when_process_exits(self):
        logger = logging.getLogger("test-probe")
        probe = proxy.ProbeProxy("/bin/dnsproxy", "/tmp/probe.log", logger)
        calls: list[int] = []

        async def fake_exec(*args, **kwargs):
            # args include -p PORT
            port = int(args[args.index("-p") + 1])
            calls.append(port)
            proc = MagicMock()
            if port == 15353:
                proc.returncode = 1  # bind failed / exited
            else:
                proc.returncode = None
                proc.pid = 4242
            proc.terminate = MagicMock()
            proc.kill = MagicMock()
            proc.wait = AsyncMock(return_value=0)
            return proc

        with patch("os.path.isfile", return_value=True), \
             patch("dns_unblock.proxy._ensure_executable"), \
             patch("dns_unblock.proxy.PROBE_BIND_WAIT", 0), \
             patch("asyncio.create_subprocess_exec", side_effect=fake_exec), \
             patch("builtins.open", mock_open()):
            port = await probe.start(["https://1.1.1.1/dns-query"])

        self.assertEqual(port, 15354)
        self.assertEqual(calls, [15353, 15354])
        self.assertTrue(probe.running)
        await probe.stop()
        self.assertFalse(probe.running)

    async def test_raises_when_all_ports_busy(self):
        logger = logging.getLogger("test-probe")
        probe = proxy.ProbeProxy("/bin/dnsproxy", "/tmp/probe.log", logger)

        async def fake_exec(*args, **kwargs):
            proc = MagicMock()
            proc.returncode = 1
            return proc

        with patch("os.path.isfile", return_value=True), \
             patch("dns_unblock.proxy._ensure_executable"), \
             patch("dns_unblock.proxy.PROBE_BIND_WAIT", 0), \
             patch("asyncio.create_subprocess_exec", side_effect=fake_exec), \
             patch("builtins.open", mock_open()):
            with self.assertRaises(OSError) as ctx:
                await probe.start(["https://1.1.1.1/dns-query"])
        self.assertIn("no free probe port", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
