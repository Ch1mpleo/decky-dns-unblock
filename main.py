import asyncio
import os
import sys
import time

# The decky plugin module is located at decky-loader/plugin
# For easy intellisense checkout the decky-loader code repo
# and add the `decky-loader/plugin/imports` path to `python.analysis.extraPaths` in `.vscode/settings.json`
import decky

# Our modules live in a uniquely named package: bare names like `settings` clash with Decky's own modules.
from dns_unblock import health, nm, providers, state
from dns_unblock.settings import Settings
from dns_unblock.watcher import DEVICE_DOWN, DEVICE_UP, Event, Watcher

# NetworkManager emits bursts of lines per change; act once things have been quiet this long.
DEBOUNCE_SECONDS = 2.0


class Plugin:
    async def _main(self):
        # Everything RPC methods rely on is set up before the first await.
        self.lock = asyncio.Lock()
        self.settings = Settings(os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "settings.json"))
        self.marker_path = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, "applied_device")
        self.device: str | None = None  # device that currently has our DNS
        self.connected_at: dict[str, float] = {}
        self.state = state.OFF
        self.message = ""
        self.loop = asyncio.get_running_loop()
        self.debounce_timer: asyncio.TimerHandle | None = None
        self.settle_timer: asyncio.TimerHandle | None = None
        self.tasks: set[asyncio.Task] = set()
        self.watcher = Watcher(self._on_event, decky.logger)
        decky.logger.info("DNS Unblock starting (Python %s), settings %s",
                          sys.version.split()[0], self.settings.to_dict())

        async with self.lock:
            stale = self._read_marker()
            if stale:
                decky.logger.info("Cleaning up DNS left on %s by a previous run", stale)
                await self._restore(stale)
            await self._reconcile()
        await self._emit_status()
        self.watcher.start()

    async def _unload(self):
        decky.logger.info("DNS Unblock unloading")
        await self._shutdown()

    async def _uninstall(self):
        decky.logger.info("DNS Unblock uninstalled")
        await self._shutdown()

    # --- RPC methods (called from the frontend) ---

    async def get_status(self) -> dict:
        return await self._status()

    async def set_enabled(self, enabled: bool) -> dict:
        async with self.lock:
            self.settings.enabled = bool(enabled)
            self.settings.save()
            await self._reconcile()
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
            await self._reconcile()
        return await self._emit_status()

    async def run_diagnostics(self) -> dict:
        device = self.device
        network_dns: list[str] = []
        try:
            device = device or await nm.get_active_wifi_device()
            if device:
                network_dns = await nm.get_dhcp_dns(device)
        except nm.CommandError as e:
            decky.logger.warning("Diagnostics: network lookup failed: %s", e)
        rows = await health.diagnose(network_dns)
        decky.logger.info("Diagnostics on %s (network DNS %s): %s", device, network_dns,
                          [(r["domain"], r["network"]["verdict"], r["system"]["verdict"]) for r in rows])
        return {"device": device, "network_dns": network_dns, "rows": rows}

    # --- NetworkManager events ---

    def _on_event(self, event: Event) -> None:
        decky.logger.info("Network event: %s %s", event.kind, event.value)
        if event.kind == DEVICE_UP:
            self.connected_at[event.value] = time.monotonic()
        elif event.kind == DEVICE_DOWN:
            self.connected_at.pop(event.value, None)
            # Deactivation drops runtime changes, so our DNS is gone from this device.
            if self.device == event.value:
                self.device = None
                self._clear_marker()
        if self.debounce_timer:
            self.debounce_timer.cancel()
        self.debounce_timer = self.loop.call_later(DEBOUNCE_SECONDS, self._spawn_reconcile)

    def _spawn_reconcile(self) -> None:
        task = asyncio.create_task(self._reconcile_and_emit())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _reconcile_and_emit(self) -> None:
        try:
            async with self.lock:
                await self._reconcile()
            await self._emit_status()
        except Exception:
            decky.logger.exception("Reconcile failed")

    async def _shutdown(self) -> None:
        for timer in (self.debounce_timer, self.settle_timer):
            if timer:
                timer.cancel()
        await self.watcher.stop()
        for task in list(self.tasks):
            task.cancel()
        async with self.lock:
            device = self.device or self._read_marker()
            if device:
                await self._restore(device)

    # --- internals (callers hold self.lock) ---

    async def _reconcile(self) -> None:
        """Read the current network facts and move to the state `state.decide` asks for."""
        if self.settle_timer:
            self.settle_timer.cancel()
            self.settle_timer = None
        try:
            device = await nm.get_active_wifi_device()
            connectivity = await nm.get_connectivity() if device else "none"
        except nm.CommandError as e:
            decky.logger.error("Could not read network state: %s", e)
            self._set_state(state.ERROR, str(e))
            return

        if self.device and self.device != device:
            if device:
                await self._restore(self.device)
            else:
                self._forget()
        waited = 0.0
        if device:
            waited = time.monotonic() - self.connected_at.setdefault(device, time.monotonic())

        decision = state.decide(
            enabled=self.settings.enabled,
            device=device,
            connectivity=connectivity,
            settled=waited >= state.SETTLE_SECONDS,
            applied=self.device is not None and self.device == device,
        )
        if decision.action == state.APPLY:
            if not await self._apply(device):
                return
        elif decision.action == state.RESTORE:
            if self.device:
                await self._restore(self.device)
        elif decision.action == state.FORGET:
            self._forget()
        self._set_state(decision.state, decision.message)

        if decision.state == state.WAITING:
            remaining = max(state.SETTLE_SECONDS - waited, 0.0) + 0.1
            self.settle_timer = self.loop.call_later(remaining, self._spawn_reconcile)

    async def _apply(self, device: str) -> bool:
        v4, v6 = providers.plain_servers(self.settings.provider, self.settings.custom_servers)
        try:
            link_dns, _ = await nm.get_link_dns(device)
            if not nm.dns_matches(link_dns, v4, v6):
                await nm.apply_dns(device, v4, v6)
                decky.logger.info("Plain DNS applied on %s: %s %s (was %s)", device, v4, v6, link_dns)
        except nm.CommandError as e:
            decky.logger.error("Applying DNS on %s failed: %s", device, e)
            await self._restore(device)
            self._set_state(state.ERROR, str(e))
            return False
        if self.device != device:
            self.device = device
            self._write_marker(device)
        return True

    async def _restore(self, device: str) -> None:
        try:
            await nm.restore(device)
            decky.logger.info("Restored network DNS on %s", device)
        except nm.CommandError as e:
            decky.logger.error("Restoring %s failed: %s", device, e)
        if self.device == device:
            self.device = None
        self._clear_marker()

    def _forget(self) -> None:
        self.device = None
        self._clear_marker()

    def _set_state(self, new_state: str, message: str = "") -> None:
        if new_state != self.state or message != self.message:
            decky.logger.info("State %s -> %s %s", self.state, new_state, message)
        self.state = new_state
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
