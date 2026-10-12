import asyncio
import os
import sys

# The decky plugin module is located at decky-loader/plugin
# For easy intellisense checkout the decky-loader code repo
# and add the `decky-loader/plugin/imports` path to `python.analysis.extraPaths` in `.vscode/settings.json`
import decky

# Our modules live in a uniquely named package: bare names like `settings` clash with Decky's own modules.
from dns_unblock import nm, providers
from dns_unblock.settings import Settings

# States reported to the frontend.
OFF = "off"
NO_NETWORK = "no_network"
ACTIVE_PLAIN = "active_plain"
ERROR = "error"


class Plugin:
    async def _main(self):
        # Everything RPC methods rely on is set up before the first await.
        self.lock = asyncio.Lock()
        self.settings = Settings(os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "settings.json"))
        self.marker_path = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, "applied_device")
        self.device: str | None = None
        self.state = OFF
        self.message = ""
        decky.logger.info("DNS Unblock starting (Python %s), settings %s",
                          sys.version.split()[0], self.settings.to_dict())

        async with self.lock:
            stale = self._read_marker()
            if self.settings.enabled:
                await self._apply()
            if stale and stale != self.device:
                decky.logger.info("Cleaning up DNS left on %s by a previous run", stale)
                await self._restore(stale)
        await self._emit_status()

    async def _unload(self):
        decky.logger.info("DNS Unblock unloading")
        async with self.lock:
            if self.device:
                await self._restore(self.device)

    async def _uninstall(self):
        decky.logger.info("DNS Unblock uninstalled")
        async with self.lock:
            device = self.device or self._read_marker()
            if device:
                await self._restore(device)

    # --- RPC methods (called from the frontend) ---

    async def get_status(self) -> dict:
        return await self._status()

    async def set_enabled(self, enabled: bool) -> dict:
        async with self.lock:
            self.settings.enabled = bool(enabled)
            self.settings.save()
            if self.settings.enabled:
                await self._apply()
            else:
                if self.device:
                    await self._restore(self.device)
                self._set_state(OFF)
        return await self._emit_status()

    async def set_mode(self, mode: str) -> dict:
        async with self.lock:
            self.settings.set_mode(mode)
            self.settings.save()
        return await self._emit_status()

    async def set_provider(self, provider: str, custom_servers: list[str] | None = None) -> dict:
        async with self.lock:
            self.settings.set_provider(provider, custom_servers)
            self.settings.save()
            if self.settings.enabled:
                await self._apply()
        return await self._emit_status()

    # --- internals (callers hold self.lock) ---

    async def _apply(self) -> None:
        try:
            device = await nm.get_active_wifi_device()
        except nm.CommandError as e:
            decky.logger.error("Could not list devices: %s", e)
            self._set_state(ERROR, str(e))
            return
        if not device:
            self._set_state(NO_NETWORK, "No connected Wi-Fi")
            return
        if self.device and self.device != device:
            await self._restore(self.device)

        v4, v6 = providers.plain_servers(self.settings.provider, self.settings.custom_servers)
        try:
            await nm.apply_dns(device, v4, v6)
        except nm.CommandError as e:
            decky.logger.error("Applying DNS on %s failed: %s", device, e)
            await self._restore(device)
            self._set_state(ERROR, str(e))
            return
        self.device = device
        self._write_marker(device)
        decky.logger.info("Plain DNS applied on %s: %s %s", device, v4, v6)
        self._set_state(ACTIVE_PLAIN)

    async def _restore(self, device: str) -> None:
        try:
            await nm.restore(device)
            decky.logger.info("Restored network DNS on %s", device)
        except nm.CommandError as e:
            decky.logger.error("Restoring %s failed: %s", device, e)
        if self.device == device:
            self.device = None
        self._clear_marker()

    def _set_state(self, state: str, message: str = "") -> None:
        if state != self.state or message != self.message:
            decky.logger.info("State %s -> %s %s", self.state, state, message)
        self.state = state
        self.message = message

    async def _status(self) -> dict:
        status = {
            **self.settings.to_dict(),
            "state": self.state,
            "message": self.message,
            "device": self.device,
            "link_dns": [],
            "current_dns": None,
            "connectivity": "unknown",
        }
        try:
            status["connectivity"] = await nm.get_connectivity()
            device = self.device or await nm.get_active_wifi_device()
            if device:
                status["device"] = device
                status["link_dns"], status["current_dns"] = await nm.get_link_dns(device)
        except nm.CommandError as e:
            decky.logger.warning("Status lookup failed: %s", e)
        return status

    async def _emit_status(self) -> dict:
        status = await self._status()
        await decky.emit("status", status)
        return status

    # The marker records which device we changed, so a crash or kill can be cleaned up on the next start.
    def _read_marker(self) -> str | None:
        try:
            with open(self.marker_path, encoding="utf-8") as f:
                return f.read().strip() or None
        except OSError:
            return None

    def _write_marker(self, device: str) -> None:
        try:
            os.makedirs(os.path.dirname(self.marker_path), exist_ok=True)
            with open(self.marker_path, "w", encoding="utf-8") as f:
                f.write(device)
        except OSError as e:
            decky.logger.warning("Could not write %s: %s", self.marker_path, e)

    def _clear_marker(self) -> None:
        try:
            os.remove(self.marker_path)
        except OSError:
            pass
