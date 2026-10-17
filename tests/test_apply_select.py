"""Selection apply path: encrypted probe → HTTPS gate → sticky / dns_only."""

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
from dns_unblock import providers, select


def _plugin():
    p = plugin_main.Plugin.__new__(plugin_main.Plugin)
    p.settings = types.SimpleNamespace(mode="auto", provider=providers.AUTOMATIC, custom_servers=[])
    p.proxy = MagicMock()
    p.proxy.available = True
    p.proxy.running = False
    p.proxy.start = AsyncMock(return_value=True)
    p.proxy.stop = AsyncMock()
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
    p.retry_timer = None
    p.retry_index = 0
    p._set_link = AsyncMock()
    p._restore = AsyncMock(return_value=True)
    p._reset_degraded_retry = MagicMock()
    p._schedule_degraded_retry = MagicMock()
    p._clear_selection = lambda: plugin_main.Plugin._clear_selection(p)
    p._set_state = lambda s, m="": plugin_main.Plugin._set_state(p, s, m)
    return p


class ApplySelectTests(unittest.IsolatedAsyncioTestCase):
    async def test_cloudflare_https_fail_google_verified(self):
        p = _plugin()
        cf = providers.candidate_order("auto", "cloudflare")[0]
        google = providers.candidate_order("auto", "google")[0]

        async def evaluate_enc(candidate):
            if candidate.provider_id == "cloudflare":
                return select.DNS_ONLY, "timeout", list(candidate.v4), list(candidate.v6)
            if candidate.provider_id == "google":
                return select.VERIFIED, "ok", list(candidate.v4), list(candidate.v6)
            return select.FAILED, "skip", [], []

        p._evaluate_encrypted = evaluate_enc
        p._evaluate_plain = AsyncMock(return_value=(select.FAILED, "skip", [], []))
        p._confirm_system = AsyncMock(return_value=(True, "ok"))

        with patch.object(plugin_main.providers, "candidate_order", return_value=[cf, google]):
            await plugin_main.Plugin._apply(p, "wlan0")

        self.assertEqual(p.active_provider, "google")
        self.assertEqual(p.observed_transport, providers.ENCRYPTED)
        self.assertEqual(p.verification, select.VERIFIED)
        self.assertEqual(p.state, "active_encrypted")

    async def test_dns_only_when_https_never_passes(self):
        p = _plugin()
        cf = providers.candidate_order("auto", "cloudflare")[0]
        p._evaluate_encrypted = AsyncMock(
            return_value=(select.DNS_ONLY, "https fail", list(cf.v4), list(cf.v6))
        )
        p._evaluate_plain = AsyncMock(return_value=(select.FAILED, "plain fail", [], []))
        p._confirm_system = AsyncMock(return_value=(True, "ok"))

        with patch.object(plugin_main.providers, "candidate_order", return_value=[cf]):
            await plugin_main.Plugin._apply(p, "wlan0")

        self.assertEqual(p.verification, select.DNS_ONLY)
        self.assertEqual(p.message, select.DNS_ONLY_MESSAGE)
        self.assertEqual(p.active_provider, "cloudflare")
        p._schedule_degraded_retry.assert_not_called()

    async def test_manual_provider_not_switched(self):
        p = _plugin()
        p.settings.provider = "cloudflare"
        cf_enc, cf_plain = providers.candidate_order("auto", "cloudflare")
        p._evaluate_encrypted = AsyncMock(return_value=(select.FAILED, "no", [], []))
        p._evaluate_plain = AsyncMock(
            return_value=(select.VERIFIED, "ok", list(cf_plain.v4), list(cf_plain.v6))
        )
        p._confirm_system = AsyncMock(return_value=(True, "ok"))

        with patch.object(plugin_main.providers, "candidate_order", return_value=[cf_enc, cf_plain]):
            await plugin_main.Plugin._apply(p, "wlan0")

        self.assertEqual(p.active_provider, "cloudflare")
        self.assertEqual(p.observed_transport, providers.PLAIN)

    async def test_system_recheck_downgrades_to_dns_only(self):
        p = _plugin()
        cf = providers.candidate_order("encrypted", "cloudflare")[0]
        p._evaluate_encrypted = AsyncMock(
            return_value=(select.VERIFIED, "ok", list(cf.v4), list(cf.v6))
        )
        p._confirm_system = AsyncMock(return_value=(False, "stale"))

        with patch.object(plugin_main.providers, "candidate_order", return_value=[cf]):
            await plugin_main.Plugin._apply(p, "wlan0")

        self.assertEqual(p.verification, select.DNS_ONLY)
        self.assertIn("unverified", p.message)


if __name__ == "__main__":
    unittest.main()
