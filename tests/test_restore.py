"""Restore / recovery helpers that can be unit-tested without a real Decky runtime."""

import logging
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

# main.py imports decky at load time; provide a minimal stub for host unit tests.
_decky = types.ModuleType("decky")
_decky.logger = logging.getLogger("decky-test")
_decky.DECKY_PLUGIN_DIR = "/tmp/decky-dns-unblock"
_decky.DECKY_PLUGIN_SETTINGS_DIR = "/tmp/decky-dns-unblock/settings"
_decky.DECKY_PLUGIN_RUNTIME_DIR = "/tmp/decky-dns-unblock/runtime"
_decky.DECKY_PLUGIN_LOG_DIR = "/tmp/decky-dns-unblock/logs"


async def _emit(*_args, **_kwargs):
    return None


_decky.emit = _emit
sys.modules.setdefault("decky", _decky)

import main as plugin_main  # noqa: E402


class RestoreRetryConstantsTests(unittest.TestCase):
    def test_retry_schedules(self):
        self.assertEqual(plugin_main.RESTORE_RETRY_DELAYS, (0.0, 1.0, 3.0))
        self.assertEqual(plugin_main.DEGRADED_RETRY_DELAYS, (30.0, 120.0, 300.0))


class RestoreMarkerLogicTests(unittest.IsolatedAsyncioTestCase):
    """Exercise Plugin._restore marker bookkeeping with nm mocked."""

    def _plugin(self):
        p = plugin_main.Plugin.__new__(plugin_main.Plugin)
        p.device = "wlan0"
        p.marker_path = "applied_device"
        p._cleared = False
        return p

    async def test_success_clears_marker_and_device(self):
        p = self._plugin()
        p._clear_marker = lambda: setattr(p, "_cleared", True)
        with patch.object(plugin_main.nm, "restore", AsyncMock()):
            ok = await plugin_main.Plugin._restore(p, "wlan0")
        self.assertTrue(ok)
        self.assertIsNone(p.device)
        self.assertTrue(p._cleared)

    async def test_failure_keeps_marker_and_device(self):
        p = self._plugin()
        p._clear_marker = lambda: setattr(p, "_cleared", True)
        with patch.object(
            plugin_main.nm, "restore", AsyncMock(side_effect=plugin_main.nm.CommandError("boom"))
        ):
            ok = await plugin_main.Plugin._restore(p, "wlan0")
        self.assertFalse(ok)
        self.assertEqual(p.device, "wlan0")
        self.assertFalse(p._cleared)

    async def test_restore_with_retries_stops_on_success(self):
        p = self._plugin()
        p._restore = AsyncMock(side_effect=[False, True])
        with patch.object(plugin_main, "RESTORE_RETRY_DELAYS", (0.0, 0.0, 0.0)):
            ok = await plugin_main.Plugin._restore_with_retries(p, "wlan0")
        self.assertTrue(ok)
        self.assertEqual(p._restore.await_count, 2)

    async def test_startup_cleanup_restores_before_kill(self):
        p = self._plugin()
        order: list[str] = []
        p._read_marker = lambda: "wlan0"
        p._restore = AsyncMock(side_effect=lambda d: order.append("restore") or True)
        p.proxy = types.SimpleNamespace(kill_stale=AsyncMock(side_effect=lambda: order.append("kill")))
        await plugin_main.Plugin._startup_cleanup(p)
        self.assertEqual(order, ["restore", "kill"])

    async def test_startup_cleanup_skips_kill_when_restore_fails(self):
        p = self._plugin()
        p._read_marker = lambda: "wlan0"
        p._restore = AsyncMock(return_value=False)
        p.proxy = types.SimpleNamespace(kill_stale=AsyncMock())
        await plugin_main.Plugin._startup_cleanup(p)
        p.proxy.kill_stale.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
