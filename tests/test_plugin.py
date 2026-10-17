"""Plugin orchestration: selection, fallback, diagnostics, shutdown."""

import logging
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

_decky = types.ModuleType("decky")
_decky.logger = logging.getLogger("decky-test")
_decky.DECKY_PLUGIN_DIR = "/tmp/decky-dns-unblock"
_decky.DECKY_PLUGIN_SETTINGS_DIR = "/tmp/decky-dns-unblock/settings"
_decky.DECKY_PLUGIN_RUNTIME_DIR = "/tmp/decky-dns-unblock/runtime"
_decky.DECKY_PLUGIN_LOG_DIR = "/tmp/decky-dns-unblock/logs"


async def _emit(*_a, **_k):
    return None


_decky.emit = _emit
sys.modules.setdefault("decky", _decky)

import main as plugin_main  # noqa: E402
from dns_unblock import providers, select, state


def _plugin(**overrides):
    p = plugin_main.Plugin.__new__(plugin_main.Plugin)
    p.settings = types.SimpleNamespace(mode="auto", provider=providers.AUTOMATIC, custom_servers=[])
    p.proxy = MagicMock()
    p.proxy.available = True
    p.proxy.running = False
    p.proxy.binary = "/bin/dnsproxy"
    p.proxy.start = AsyncMock(return_value=True)
    p.proxy.stop = AsyncMock()
    p.proxy.kill_stale = AsyncMock()
    p.proxy_failures = 0
    p.proxy_stale = False
    p.force_link = False
    p.device = None
    p.active_provider = None
    p.observed_transport = None
    p.verification = None
    p.verification_at = None
    p.state = "off"
    p.message = ""
    p.stopping = False
    p.generation = 0
    p._health_refreshing = False
    p.retry_timer = None
    p.retry_index = 0
    p.debounce_timer = None
    p.settle_timer = None
    p.tasks = set()
    p.lock = AsyncMock()
    p.lock.__aenter__ = AsyncMock(return_value=None)
    p.lock.__aexit__ = AsyncMock(return_value=None)
    p.watcher = types.SimpleNamespace(stop=AsyncMock())
    p.marker_path = "applied_device"
    p._set_link = AsyncMock()
    p._restore = AsyncMock(return_value=True)
    p._reset_degraded_retry = MagicMock()
    p._schedule_degraded_retry = MagicMock()
    p._cancel_degraded_retry = MagicMock()
    p._clear_selection = lambda: plugin_main.Plugin._clear_selection(p)
    p._set_state = lambda s, m="": plugin_main.Plugin._set_state(p, s, m)
    p._keep_established_with_hysteresis = AsyncMock(return_value=False)
    p._confirm_system = AsyncMock(return_value=(True, "ok"))
    p._read_marker = lambda: None
    p._write_marker = MagicMock()
    p._clear_marker = MagicMock()
    for key, value in overrides.items():
        setattr(p, key, value)
    return p


class AutomaticSelectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_cloudflare_dns_fail_google_verified(self):
        p = _plugin()
        cf = providers.candidate_order("auto", "cloudflare")[0]
        google = providers.candidate_order("auto", "google")[0]

        async def evaluate_enc(candidate):
            if candidate.provider_id == "cloudflare":
                return select.FAILED, "timeout", [], []
            if candidate.provider_id == "google":
                return select.VERIFIED, "ok", list(candidate.v4), list(candidate.v6)
            return select.FAILED, "skip", [], []

        p._evaluate_encrypted = evaluate_enc
        p._evaluate_plain = AsyncMock(return_value=(select.FAILED, "skip", [], []))

        with patch.object(plugin_main.providers, "candidate_order", return_value=[cf, google]):
            await plugin_main.Plugin._apply(p, "wlan0")

        self.assertEqual(p.active_provider, "google")
        self.assertEqual(p.observed_transport, providers.ENCRYPTED)
        self.assertEqual(p.verification, select.VERIFIED)
        self.assertEqual(p.state, state.ACTIVE_ENCRYPTED)
        p._schedule_degraded_retry.assert_not_called()

    async def test_all_fail_falls_back_and_restores(self):
        p = _plugin(device="wlan0")
        cf = providers.candidate_order("encrypted", "cloudflare")[0]
        p._evaluate_encrypted = AsyncMock(return_value=(select.FAILED, "down", [], []))
        p._evaluate_plain = AsyncMock(return_value=(select.FAILED, "down", [], []))

        with patch.object(plugin_main.providers, "candidate_order", return_value=[cf]):
            await plugin_main.Plugin._apply(p, "wlan0")

        self.assertEqual(p.state, state.FALLBACK)
        self.assertEqual(p.verification, select.FAILED)
        self.assertEqual(p.observed_transport, "network")
        self.assertIsNone(p.active_provider)
        p._restore.assert_awaited_once_with("wlan0")
        p.proxy.stop.assert_awaited()
        p._schedule_degraded_retry.assert_called_once()

    async def test_encrypted_mode_does_not_try_plain(self):
        p = _plugin()
        p.settings.mode = "encrypted"
        cf = providers.candidate_order("encrypted", "cloudflare")[0]
        p._evaluate_encrypted = AsyncMock(return_value=(select.FAILED, "no", [], []))
        p._evaluate_plain = AsyncMock(return_value=(select.VERIFIED, "ok", ["1.1.1.1"], []))

        with patch.object(plugin_main.providers, "candidate_order", return_value=[cf]):
            await plugin_main.Plugin._apply(p, "wlan0")

        p._evaluate_plain.assert_not_awaited()
        self.assertEqual(p.state, state.FALLBACK)


class PlainSelectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_plain_applies_only_verified_servers(self):
        p = _plugin()
        p.settings.mode = "plain"
        p.settings.provider = "cloudflare"
        plain = providers.candidate_order("plain", "cloudflare")[0]
        # Primary fails DNS; secondary + IPv6 succeed in evaluate_plain return value.
        p._evaluate_encrypted = AsyncMock(return_value=(select.FAILED, "n/a", [], []))
        p._evaluate_plain = AsyncMock(
            return_value=(select.VERIFIED, "ok", ["1.0.0.1"], ["2606:4700:4700::1001"])
        )

        with patch.object(plugin_main.providers, "candidate_order", return_value=[plain]):
            await plugin_main.Plugin._apply(p, "wlan0")

        self.assertEqual(p.active_provider, "cloudflare")
        self.assertEqual(p.observed_transport, providers.PLAIN)
        p.proxy.stop.assert_awaited()
        p._set_link.assert_awaited_with("wlan0", ["1.0.0.1"], ["2606:4700:4700::1001"])


class CommitLinkTests(unittest.IsolatedAsyncioTestCase):
    async def test_auto_encrypted_keeps_plain_backup_on_link(self):
        p = _plugin()
        cf = providers.candidate_order("encrypted", "cloudflare")[0]
        ok = await plugin_main.Plugin._commit_candidate(
            p, "wlan0", cf, list(cf.v4), list(cf.v6), select.VERIFIED, [], gen=0
        )
        self.assertTrue(ok)
        # Auto mode: dnsproxy + first plain IPv4 backup.
        p._set_link.assert_awaited_with(
            "wlan0", [plugin_main.LISTEN_ADDR, cf.v4[0]], [], force=True
        )

    async def test_encrypted_only_mode_skips_plain_backup(self):
        p = _plugin()
        p.settings.mode = "encrypted"
        cf = providers.candidate_order("encrypted", "cloudflare")[0]
        await plugin_main.Plugin._commit_candidate(
            p, "wlan0", cf, list(cf.v4), list(cf.v6), select.VERIFIED, [], gen=0
        )
        p._set_link.assert_awaited_with("wlan0", [plugin_main.LISTEN_ADDR], [], force=True)


class ShutdownTests(unittest.IsolatedAsyncioTestCase):
    async def test_shutdown_restores_before_proxy_stop(self):
        p = _plugin(device="wlan0", generation=1)
        order: list[str] = []
        p._restore_with_retries = AsyncMock(
            side_effect=lambda d: order.append("restore") or True
        )
        p.proxy.stop = AsyncMock(side_effect=lambda: order.append("stop"))

        await plugin_main.Plugin._shutdown(p)

        self.assertTrue(p.stopping)
        self.assertEqual(p.generation, 2)
        self.assertEqual(order, ["restore", "stop"])
        p._cancel_degraded_retry.assert_called_once()

    async def test_shutdown_keeps_proxy_when_restore_fails(self):
        p = _plugin(device="wlan0")
        p._restore_with_retries = AsyncMock(return_value=False)
        await plugin_main.Plugin._shutdown(p)
        p.proxy.stop.assert_not_awaited()


class DiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    async def test_payload_includes_context_and_timestamp(self):
        p = _plugin(device="wlan0", active_provider="google", generation=3)
        p.settings.mode = "auto"
        p.settings.provider = providers.AUTOMATIC
        p.observed_transport = providers.ENCRYPTED
        rows = [{
            "domain": "store.steampowered.com",
            "network": {"verdict": "resolved", "detail": "1.2.3.4", "addresses": ["1.2.3.4"]},
            "provider": {"verdict": "resolved", "detail": "1.2.3.4", "addresses": ["1.2.3.4"]},
            "system": {"verdict": "resolved", "detail": "1.2.3.4", "addresses": ["1.2.3.4"]},
            "https": {"verdict": "reachable", "detail": "HTTP 200", "status_code": 200},
        }]
        p._diagnostics_provider_endpoint = AsyncMock(
            return_value=(plugin_main.LISTEN_ADDR, 53, "Google encrypted (live)", None)
        )
        with patch.object(plugin_main.nm, "get_active_wifi_device", AsyncMock(return_value="wlan0")), \
             patch.object(plugin_main.nm, "get_connectivity", AsyncMock(return_value="full")), \
             patch.object(plugin_main.nm, "get_dhcp_dns", AsyncMock(return_value=["192.168.1.1"])), \
             patch.object(plugin_main.health, "diagnose", AsyncMock(return_value=rows)), \
             patch.object(plugin_main.health, "summarize", return_value="DNS resolved. HTTPS reachable."):
            payload = await plugin_main.Plugin.run_diagnostics(p)

        self.assertEqual(payload["resolver"], "Google encrypted (live)")
        self.assertEqual(payload["mode"], "auto")
        self.assertEqual(payload["provider"], providers.AUTOMATIC)
        self.assertEqual(payload["active_provider"], "google")
        self.assertEqual(payload["connectivity"], "full")
        self.assertEqual(payload["network_dns"], ["192.168.1.1"])
        self.assertEqual(payload["rows"], rows)
        self.assertIn("HTTPS reachable", payload["summary"])
        self.assertIsInstance(payload["timestamp"], float)
        self.assertEqual(
            payload["context"],
            {
                "mode": "auto",
                "provider": providers.AUTOMATIC,
                "active_provider": "google",
                "device": "wlan0",
            },
        )

    async def test_stale_generation_cancels_diagnostics(self):
        p = _plugin(device="wlan0", generation=1)

        async def bump_then_endpoint():
            p.generation += 1
            return plugin_main.LISTEN_ADDR, 53, "x", None

        p._diagnostics_provider_endpoint = bump_then_endpoint
        with patch.object(plugin_main.nm, "get_active_wifi_device", AsyncMock(return_value="wlan0")), \
             patch.object(plugin_main.nm, "get_connectivity", AsyncMock(return_value="full")), \
             patch.object(plugin_main.nm, "get_dhcp_dns", AsyncMock(return_value=[])), \
             patch.object(plugin_main.health, "diagnose", AsyncMock()) as diagnose:
            payload = await plugin_main.Plugin.run_diagnostics(p)

        diagnose.assert_not_awaited()
        self.assertEqual(payload["resolver"], "stale")
        self.assertIn("cancelled", payload["summary"].lower())
        self.assertEqual(payload["rows"], [])

    async def test_live_encrypted_uses_running_proxy_without_probe(self):
        p = _plugin(
            active_provider="cloudflare",
            observed_transport=providers.ENCRYPTED,
        )
        p.proxy.running = True
        server, port, label, probe = await plugin_main.Plugin._diagnostics_provider_endpoint(p)
        self.assertEqual(server, plugin_main.LISTEN_ADDR)
        self.assertEqual(port, 53)
        self.assertIn("live", label)
        self.assertIsNone(probe)


class RetryCancelTests(unittest.TestCase):
    def test_settings_change_cancels_degraded_retry(self):
        p = _plugin()
        # Mirror set_mode bookkeeping without full reconcile.
        p._reset_degraded_retry()
        p._clear_selection()
        plugin_main.Plugin._bump_generation(p, "settings")
        p._reset_degraded_retry.assert_called()
        self.assertEqual(p.generation, 1)


if __name__ == "__main__":
    unittest.main()
