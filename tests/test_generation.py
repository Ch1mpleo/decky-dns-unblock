"""Generation guards, health-cache staleness, and establish-provider hysteresis."""

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
    p.proxy.start = AsyncMock(return_value=False)
    p.proxy.stop = AsyncMock()
    p.proxy_failures = 0
    p.proxy_stale = False
    p.force_link = False
    p.device = "wlan0"
    p.active_provider = "cloudflare"
    p.observed_transport = providers.ENCRYPTED
    p.verification = select.VERIFIED
    p.verification_at = 0.0
    p.state = "active_encrypted"
    p.message = ""
    p.stopping = False
    p.generation = 1
    p._health_refreshing = False
    p.retry_timer = None
    p.retry_index = 0
    p._set_link = AsyncMock()
    p._restore = AsyncMock(return_value=True)
    p._reset_degraded_retry = MagicMock()
    p._schedule_degraded_retry = MagicMock()
    p._confirm_system = AsyncMock(return_value=(True, "ok"))
    p._set_state = lambda s, m="": plugin_main.Plugin._set_state(p, s, m)
    p._clear_selection = lambda: plugin_main.Plugin._clear_selection(p)
    return p


class GenerationTests(unittest.TestCase):
    def test_generation_ok_and_bump(self):
        p = _plugin()
        self.assertTrue(plugin_main.Plugin._generation_ok(p, 1, "x"))
        plugin_main.Plugin._bump_generation(p, "test")
        self.assertEqual(p.generation, 2)
        self.assertFalse(plugin_main.Plugin._generation_ok(p, 1, "stale"))

    def test_health_cache_stale(self):
        p = _plugin()
        p.verification_at = plugin_main.time.time()
        self.assertFalse(plugin_main.Plugin._health_cache_stale(p))
        p.verification_at = plugin_main.time.time() - plugin_main.HEALTH_CACHE_SECONDS - 1
        self.assertTrue(plugin_main.Plugin._health_cache_stale(p))
        p.state = "off"
        self.assertFalse(plugin_main.Plugin._health_cache_stale(p))


class HysteresisTests(unittest.IsolatedAsyncioTestCase):
    async def test_single_failure_keeps_provider(self):
        p = _plugin()
        cf = providers.candidate_order("auto", "cloudflare")[0]
        calls = {"n": 0}

        async def evaluate(candidate):
            calls["n"] += 1
            if calls["n"] == 1:
                return select.FAILED, "once", [], []
            return select.VERIFIED, "ok", list(candidate.v4), list(candidate.v6)

        p._evaluate_encrypted = evaluate
        p._evaluate_plain = AsyncMock(return_value=(select.FAILED, "n/a", [], []))
        p._commit_candidate = AsyncMock(return_value=True)

        with patch.object(plugin_main, "HYSTERESIS_SECONDS", 0):
            kept = await plugin_main.Plugin._keep_established_with_hysteresis(
                p, "wlan0", [cf], p.generation, []
            )
        self.assertTrue(kept)
        self.assertEqual(calls["n"], 2)
        p._commit_candidate.assert_awaited()

    async def test_two_failures_allow_replacement(self):
        p = _plugin()
        cf = providers.candidate_order("auto", "cloudflare")[0]
        p._evaluate_encrypted = AsyncMock(return_value=(select.FAILED, "down", [], []))

        with patch.object(plugin_main, "HYSTERESIS_SECONDS", 0):
            kept = await plugin_main.Plugin._keep_established_with_hysteresis(
                p, "wlan0", [cf], p.generation, []
            )
        self.assertFalse(kept)

    async def test_stale_generation_discards_commit(self):
        p = _plugin()
        cf = providers.candidate_order("encrypted", "cloudflare")[0]
        p.generation = 5
        ok = await plugin_main.Plugin._commit_candidate(
            p, "wlan0", cf, list(cf.v4), list(cf.v6), select.VERIFIED, [], gen=4
        )
        self.assertFalse(ok)
        p.proxy.start.assert_not_awaited()

    async def test_apply_aborts_when_generation_changes_mid_loop(self):
        p = _plugin()
        p.active_provider = None
        p.verification = None
        p.device = None
        cf = providers.candidate_order("encrypted", "cloudflare")[0]
        google = providers.candidate_order("encrypted", "google")[0]

        async def evaluate(candidate):
            if candidate.provider_id == "cloudflare":
                p.generation += 1  # network switch during probe
                return select.FAILED, "x", [], []
            return select.VERIFIED, "ok", list(candidate.v4), list(candidate.v6)

        p._evaluate_encrypted = evaluate
        p._evaluate_plain = AsyncMock(return_value=(select.FAILED, "n/a", [], []))
        p._commit_candidate = AsyncMock(return_value=True)
        p._keep_established_with_hysteresis = AsyncMock(return_value=False)

        with patch.object(plugin_main.providers, "candidate_order", return_value=[cf, google]):
            await plugin_main.Plugin._apply(p, "wlan0")

        p._commit_candidate.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
