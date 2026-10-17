import asyncio
import os
import sys
import time

# The decky plugin module is located at decky-loader/plugin
# For easy intellisense checkout the decky-loader code repo
# and add the `decky-loader/plugin/imports` path to `python.analysis.extraPaths` in `.vscode/settings.json`
import decky

# Our modules live in a uniquely named package: bare names like `settings` clash with Decky's own modules.
from dns_unblock import health, nm, providers, select, state
from dns_unblock.proxy import LISTEN_ADDR, ProbeProxy, Proxy
from dns_unblock.settings import Settings
from dns_unblock.watcher import DEVICE_DOWN, DEVICE_UP, Event, Watcher

# NetworkManager emits bursts of lines per change; act once things have been quiet this long.
DEBOUNCE_SECONDS = 2.0
# After this many dnsproxy crashes, stop trying encrypted DNS until the next connection or settings change.
PROXY_FAILURE_LIMIT = 3
# Unload/disable restore attempts: immediate, then 1s, then 3s.
RESTORE_RETRY_DELAYS = (0.0, 1.0, 3.0)
# Degraded (fallback/error) re-try schedule: 30s, 2m, then every 5m.
DEGRADED_RETRY_DELAYS = (30.0, 120.0, 300.0)
# Panel-open health refresh: reuse results younger than this.
HEALTH_CACHE_SECONDS = 60.0
# Require two failed checks this far apart before replacing an established provider.
HYSTERESIS_SECONDS = 1.0


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
        self.retry_timer: asyncio.TimerHandle | None = None
        self.retry_index = 0
        self.tasks: set[asyncio.Task] = set()
        self.watcher = Watcher(self._on_event, decky.logger)
        self.proxy = Proxy(
            binary=os.path.join(decky.DECKY_PLUGIN_DIR, "bin", "dnsproxy"),
            pid_path=os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, "dnsproxy.pid"),
            log_path=os.path.join(decky.DECKY_PLUGIN_LOG_DIR, "dnsproxy.log"),
            logger=decky.logger,
            on_exit=self._on_proxy_exit,
        )
        self.proxy_failures = 0
        # resolved keeps using the second link server after dnsproxy hiccups; re-applying moves it back.
        self.force_link = False
        # After a reconnect dnsproxy's pooled HTTPS connections are dead (requests hang until its timeout) and its
        # cache would hide that from verify, so it is restarted before the next use.
        self.proxy_stale = False
        self.stopping = False
        # Observed selection (not the user preference in settings.provider).
        self.active_provider: str | None = None
        self.observed_transport: str | None = None
        self.verification: str | None = None
        self.verification_at: float | None = None
        # Bumped on network/settings/shutdown so in-flight probes discard stale results.
        self.generation = 0
        self._health_refreshing = False
        decky.logger.info("DNS Unblock starting (Python %s), settings %s",
                          sys.version.split()[0], self.settings.to_dict())
        if not self.proxy.available:
            decky.logger.warning("dnsproxy not found at %s, encrypted DNS unavailable", self.proxy.binary)

        async with self.lock:
            await self._startup_cleanup()
            await self._reconcile()
        await self._emit_status()
        # Decky can unload a plugin while _main is still running (seen during deploys).
        if not self.stopping:
            self.watcher.start()

    async def _unload(self):
        decky.logger.info("DNS Unblock unloading")
        await self._shutdown()

    async def _uninstall(self):
        decky.logger.info("DNS Unblock uninstalled")
        await self._shutdown()

    # --- RPC methods (called from the frontend) ---

    async def get_status(self) -> dict:
        status = await self._status()
        if (self.state == state.ACTIVE_ENCRYPTED and status["current_dns"]
                and status["current_dns"] != LISTEN_ADDR and not self.lock.locked()):
            decky.logger.info("resolved switched to %s, moving it back to dnsproxy", status["current_dns"])
            self.force_link = True
            self._spawn_reconcile()
        elif self._health_cache_stale() and not self.lock.locked() and not self._health_refreshing:
            self._spawn_health_refresh()
        return status

    async def set_enabled(self, enabled: bool) -> dict:
        async with self.lock:
            self.settings.enabled = bool(enabled)
            self.settings.save()
            self.proxy_failures = 0
            self._reset_degraded_retry()
            self._clear_selection()
            self._bump_generation("settings")
            await self._reconcile()
        return await self._emit_status()

    async def set_mode(self, mode: str) -> dict:
        async with self.lock:
            self.settings.set_mode(mode)
            self.settings.save()
            self.proxy_failures = 0
            self._reset_degraded_retry()
            self._clear_selection()
            self._bump_generation("settings")
            await self._reconcile()
        return await self._emit_status()

    async def set_provider(self, provider: str, custom_servers: list[str] | None = None) -> dict:
        async with self.lock:
            self.settings.set_provider(provider, custom_servers)
            self.settings.save()
            self.proxy_failures = 0
            self._reset_degraded_retry()
            self._clear_selection()
            self._bump_generation("settings")
            await self._reconcile()
        return await self._emit_status()

    async def run_diagnostics(self) -> dict:
        """Explicit diagnostics: Network vs configured/active provider vs Deck, plus HTTPS."""
        gen = self.generation
        device = self.device
        network_dns: list[str] = []
        connectivity = "unknown"
        try:
            device = device or await nm.get_active_wifi_device()
            connectivity = await nm.get_connectivity() if device else "none"
            if device:
                network_dns = await nm.get_dhcp_dns(device)
        except nm.CommandError as e:
            decky.logger.warning("Diagnostics: network lookup failed: %s", e)

        if not self._generation_ok(gen, "diagnostics before provider probe"):
            return self._diagnostics_stale_payload(device, network_dns, connectivity)

        server, port, resolver_label, probe = await self._diagnostics_provider_endpoint()
        try:
            if not self._generation_ok(gen, "diagnostics before diagnose"):
                return self._diagnostics_stale_payload(device, network_dns, connectivity)
            rows = await health.diagnose(network_dns, server, provider_port=port)
            summary = health.summarize(rows, resolver_label=resolver_label)
        finally:
            if probe is not None:
                await probe.stop()

        if not self._generation_ok(gen, "diagnostics before return"):
            return self._diagnostics_stale_payload(device, network_dns, connectivity)

        payload = {
            "timestamp": time.time(),
            "mode": self.settings.mode,
            "provider": self.settings.provider,
            "active_provider": self.active_provider,
            "connectivity": connectivity,
            "device": device,
            "network_dns": network_dns,
            "resolver": resolver_label,
            "rows": rows,
            "summary": summary,
            "context": {
                "mode": self.settings.mode,
                "provider": self.settings.provider,
                "active_provider": self.active_provider,
                "device": device,
            },
        }
        decky.logger.info(
            "Diagnostics on %s (resolver %s, network DNS %s, state %s): %s -> %s",
            device, resolver_label, network_dns, self.state,
            [(r["domain"], r["network"]["verdict"], r["provider"]["verdict"],
              r["system"]["verdict"], r["https"]["verdict"]) for r in rows],
            summary,
        )
        return payload

    def _diagnostics_stale_payload(self, device, network_dns, connectivity) -> dict:
        return {
            "timestamp": time.time(),
            "mode": self.settings.mode,
            "provider": self.settings.provider,
            "active_provider": self.active_provider,
            "connectivity": connectivity,
            "device": device,
            "network_dns": network_dns,
            "resolver": "stale",
            "rows": [],
            "summary": "Diagnostics cancelled (network or settings changed).",
            "context": {
                "mode": self.settings.mode,
                "provider": self.settings.provider,
                "active_provider": self.active_provider,
                "device": device,
            },
        }

    async def _diagnostics_provider_endpoint(
        self,
    ) -> tuple[str | None, int, str, ProbeProxy | None]:
        """Pick the provider column target without changing the live link DNS.

        Prefers the active resolver; otherwise probes the configured preference (Automatic may
        try encrypted candidates via a temporary dnsproxy).
        """
        # Live encrypted path already on the link.
        if (
            self.active_provider
            and self.observed_transport == providers.ENCRYPTED
            and self.proxy.running
        ):
            label = f"{select.provider_display_name(self.active_provider)} encrypted (live)"
            return LISTEN_ADDR, 53, label, None

        # Live plain path.
        if self.active_provider and self.observed_transport == providers.PLAIN:
            candidates = providers.candidate_order("plain", self.active_provider, self.settings.custom_servers)
            if candidates:
                server = (list(candidates[0].v4) or list(candidates[0].v6) or [None])[0]
                if server:
                    label = f"{select.provider_display_name(self.active_provider)} plain"
                    return server, 53, label, None

        preference = self.settings.provider
        # Configured Automatic while inactive: try encrypted candidates without applying.
        if preference == providers.AUTOMATIC:
            if not self.proxy.available:
                return None, 53, "Automatic (dnsproxy missing)", None
            for candidate in providers.candidate_order("encrypted", providers.AUTOMATIC):
                probe = ProbeProxy(
                    self.proxy.binary,
                    os.path.join(decky.DECKY_PLUGIN_LOG_DIR, "dnsproxy-probe.log"),
                    decky.logger,
                )
                try:
                    port = await probe.start(list(candidate.doh))
                    ok, _ = await health.verify(
                        LISTEN_ADDR, timeout=health.DNS_TIMEOUT, attempts=2, port=port
                    )
                    if ok:
                        label = f"{select.provider_display_name(candidate.provider_id)} encrypted (probe)"
                        return LISTEN_ADDR, port, label, probe
                except OSError:
                    pass
                await probe.stop()
            # Fall through to first plain Automatic candidate.
            plains = providers.candidate_order("plain", providers.AUTOMATIC)
            if plains:
                server = (list(plains[0].v4) or [None])[0]
                label = f"{select.provider_display_name(plains[0].provider_id)} plain (probe)"
                return server, 53, label, None
            return None, 53, "Automatic (no candidate)", None

        if preference == providers.CUSTOM:
            try:
                v4, v6 = providers.plain_servers(preference, self.settings.custom_servers)
            except ValueError:
                return None, 53, "Custom (invalid)", None
            server = (v4 or v6 or [None])[0]
            return server, 53, "Custom plain", None

        # Explicit preset: prefer encrypted probe for parity with selection.
        doh = providers.doh_upstreams(preference)
        if doh and self.proxy.available:
            probe = ProbeProxy(
                self.proxy.binary,
                os.path.join(decky.DECKY_PLUGIN_LOG_DIR, "dnsproxy-probe.log"),
                decky.logger,
            )
            try:
                port = await probe.start(doh)
                label = f"{select.provider_display_name(preference)} encrypted (probe)"
                return LISTEN_ADDR, port, label, probe
            except OSError as e:
                await probe.stop()
                decky.logger.warning("Diagnostics probe failed: %s", e)
        v4, v6 = providers.plain_servers(preference, self.settings.custom_servers)
        server = (v4 or v6 or [None])[0]
        return server, 53, f"{select.provider_display_name(preference)} plain", None

    # --- events (NetworkManager, dnsproxy) ---

    def _on_event(self, event: Event) -> None:
        decky.logger.info("Network event: %s %s", event.kind, event.value)
        if event.kind == DEVICE_UP:
            self.connected_at[event.value] = time.monotonic()
            self.proxy_failures = 0
            self._reset_degraded_retry()
            # New connection: re-select rather than keep a sticky provider from the previous network.
            self._clear_selection()
            self._bump_generation("device_up")
        elif event.kind == DEVICE_DOWN:
            self.connected_at.pop(event.value, None)
            self.proxy_stale = True
            self._cancel_degraded_retry()
            self._bump_generation("device_down")
            # Do not clear the marker here: reconcile confirms the device is gone, then FORGET.
            # Clearing early could drop recovery evidence if restore is still owed.
        if self.debounce_timer:
            self.debounce_timer.cancel()
        self.debounce_timer = self.loop.call_later(DEBOUNCE_SECONDS, self._spawn_reconcile)

    def _on_proxy_exit(self, code: int) -> None:
        self.proxy_failures += 1
        self.force_link = True
        self._spawn_reconcile()

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
        self.stopping = True
        self._bump_generation("shutdown")
        self._cancel_degraded_retry()
        for timer in (self.debounce_timer, self.settle_timer):
            if timer:
                timer.cancel()
        await self.watcher.stop()
        for task in list(self.tasks):
            task.cancel()
        async with self.lock:
            device = self.device or self._read_marker()
            if device:
                ok = await self._restore_with_retries(device)
                if ok:
                    await self.proxy.stop()
                else:
                    decky.logger.error(
                        "Unload restore failed on %s after retries; keeping marker and leaving dnsproxy "
                        "running for startup recovery",
                        device,
                    )
            else:
                await self.proxy.stop()

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
                if not await self._restore(self.device):
                    self._set_state(state.ERROR, f"Could not restore network DNS on {self.device}")
                    self._schedule_degraded_retry()
                    return
            else:
                # Active Wi-Fi is gone: runtime DNS was dropped with the link.
                self._forget()
                await self.proxy.stop()
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
            await self._apply(device)
            return
        if decision.action == state.RESTORE:
            target = self.device or self._read_marker()
            if target:
                if await self._restore(target):
                    await self.proxy.stop()
                    self._set_state(decision.state, decision.message)
                    self._cancel_degraded_retry()
                else:
                    # Never report a clean Off while restoration still owes work.
                    self._set_state(state.ERROR, f"Could not restore network DNS on {target}")
                    self._schedule_degraded_retry()
            else:
                await self.proxy.stop()
                self._set_state(decision.state, decision.message)
                self._cancel_degraded_retry()
            return
        if decision.action == state.FORGET:
            self._forget()
            await self.proxy.stop()
            self._cancel_degraded_retry()
        self._set_state(decision.state, decision.message)

        if decision.state == state.WAITING:
            remaining = max(state.SETTLE_SECONDS - waited, 0.0) + 0.1
            self.settle_timer = self.loop.call_later(remaining, self._spawn_reconcile)

    async def _apply(self, device: str) -> None:
        """Evaluate candidates (DNS + HTTPS); apply the first fully verified, else a DNS-only backup."""
        gen = self.generation
        candidates = select.sticky_first(
            providers.candidate_order(
                self.settings.mode, self.settings.provider, self.settings.custom_servers
            ),
            self.active_provider,
            self.observed_transport,
        )
        encrypted = [c for c in candidates if c.transport == providers.ENCRYPTED]
        encrypted_ok = (
            self.proxy.available and bool(encrypted) and self.proxy_failures < PROXY_FAILURE_LIMIT
        )
        notes: list[str] = []
        if self.settings.mode != state.PLAIN and not encrypted:
            notes.append("Custom servers have no encrypted DNS")
        elif not encrypted_ok and self.settings.mode != state.PLAIN:
            notes.append(self._encrypted_unavailable_reason())

        # Established provider: require two failures before replacing (hysteresis).
        if await self._keep_established_with_hysteresis(device, candidates, gen, notes):
            return
        if not self._generation_ok(gen, "apply after hysteresis"):
            return

        dns_only_backup: tuple[providers.Candidate, list[str], list[str], str] | None = None
        skip_sticky = (
            self.active_provider is not None
            and self.verification in (select.VERIFIED, select.DNS_ONLY)
        )

        for candidate in candidates:
            if skip_sticky and (
                candidate.provider_id == self.active_provider
                and candidate.transport == self.observed_transport
            ):
                # Already failed hysteresis for this candidate; try the rest.
                continue
            if candidate.transport == providers.ENCRYPTED and not encrypted_ok:
                continue
            label = providers.candidate_label(candidate)
            try:
                if candidate.transport == providers.ENCRYPTED:
                    outcome, detail, v4, v6 = await self._evaluate_encrypted(candidate)
                else:
                    outcome, detail, v4, v6 = await self._evaluate_plain(candidate)
            except nm.CommandError as e:
                if not self._generation_ok(gen, "apply error"):
                    return
                decky.logger.error("Applying DNS on %s failed: %s", device, e)
                restored = await self._restore(device)
                if restored:
                    await self.proxy.stop()
                self._clear_selection()
                self._set_state(state.ERROR, str(e))
                self._schedule_degraded_retry()
                return

            if not self._generation_ok(gen, f"after evaluating {label}"):
                return

            if outcome == select.VERIFIED:
                await self._commit_candidate(device, candidate, v4, v6, select.VERIFIED, notes, gen=gen)
                return
            if outcome == select.DNS_ONLY and dns_only_backup is None:
                dns_only_backup = (candidate, v4, v6, detail)
                notes.append(f"{label}: {select.DNS_ONLY_MESSAGE}")
                decky.logger.warning("%s DNS ok but HTTPS unverified on %s: %s", label, device, detail)
                continue
            decky.logger.warning("%s check failed on %s: %s", label, device, detail)
            notes.append(f"{label} failed ({detail})")

        if not self._generation_ok(gen, "apply before dns_only/fallback"):
            return

        if dns_only_backup:
            candidate, v4, v6, _detail = dns_only_backup
            await self._commit_candidate(
                device, candidate, v4, v6, select.DNS_ONLY, notes,
                message=select.DNS_ONLY_MESSAGE, gen=gen,
            )
            return

        if self.device:
            restored = await self._restore(self.device)
            if restored:
                await self.proxy.stop()
        else:
            await self.proxy.stop()
        self._clear_selection()
        self.observed_transport = "network"
        self.verification = select.FAILED
        self.verification_at = time.time()
        self._set_state(state.FALLBACK, "; ".join(notes) or "No usable DNS")
        self._schedule_degraded_retry()

    def _encrypted_unavailable_reason(self) -> str:
        if not self.proxy.available:
            return "dnsproxy is missing"
        return "dnsproxy keeps crashing"

    async def _evaluate_encrypted(
        self, candidate: providers.Candidate
    ) -> tuple[str, str, list[str], list[str]]:
        """Probe via an isolated dnsproxy; leave the live resolver untouched."""
        probe = ProbeProxy(
            self.proxy.binary,
            os.path.join(decky.DECKY_PLUGIN_LOG_DIR, "dnsproxy-probe.log"),
            decky.logger,
        )
        try:
            port = await probe.start(list(candidate.doh))
            evaluation = await health.evaluate_resolver(
                LISTEN_ADDR,
                port=port,
                attempts=3,
                overall_timeout=health.PROVIDER_TIMEOUT,
            )
        except OSError as e:
            return select.FAILED, f"dnsproxy: {e}", [], []
        finally:
            await probe.stop()

        v4, v6 = list(candidate.v4), list(candidate.v6)
        if evaluation.verified:
            return select.VERIFIED, evaluation.detail, v4, v6
        if evaluation.dns_ok:
            return select.DNS_ONLY, evaluation.detail, v4, v6
        return select.FAILED, evaluation.detail, [], []

    async def _evaluate_plain(
        self, candidate: providers.Candidate
    ) -> tuple[str, str, list[str], list[str]]:
        """Test each plain server independently; HTTPS uses candidate-resolved addresses only."""
        v4, v6, detail = await health.verify_plain_servers(list(candidate.v4), list(candidate.v6))
        if not v4 and not v6:
            return select.FAILED, detail, [], []
        server = (v4 or v6)[0]
        evaluation = await health.evaluate_resolver(
            server, overall_timeout=health.PROVIDER_TIMEOUT
        )
        if evaluation.verified:
            return select.VERIFIED, evaluation.detail, v4, v6
        # Servers already passed dual-domain DNS in verify_plain_servers.
        return select.DNS_ONLY, evaluation.detail, v4, v6

    async def _commit_candidate(
        self,
        device: str,
        candidate: providers.Candidate,
        v4: list[str],
        v6: list[str],
        verification: str,
        notes: list[str],
        message: str = "",
        gen: int | None = None,
    ) -> bool:
        if gen is not None and not self._generation_ok(gen, "before commit"):
            return False
        if candidate.transport == providers.ENCRYPTED:
            if self.proxy_stale:
                await self.proxy.stop()
                self.proxy_stale = False
            try:
                started = await self.proxy.start(list(candidate.doh))
            except OSError as e:
                raise nm.CommandError(f"dnsproxy: {e}") from e
            link = [LISTEN_ADDR] + (list(candidate.v4[:1]) if self.settings.mode == "auto" else [])
            await self._set_link(device, link, [], force=started or self.force_link)
            self.force_link = False
        else:
            await self.proxy.stop()
            await self._set_link(device, v4, v6)

        if gen is not None and not self._generation_ok(gen, "after set_link"):
            return False

        system_ok, system_detail = await self._confirm_system()
        if gen is not None and not self._generation_ok(gen, "after system confirm"):
            return False
        if verification == select.VERIFIED and not system_ok:
            decky.logger.warning("System DNS recheck failed after apply: %s", system_detail)
            verification = select.DNS_ONLY
            message = select.DNS_ONLY_MESSAGE

        self.active_provider = candidate.provider_id
        self.observed_transport = candidate.transport
        self.verification = verification
        self.verification_at = time.time()
        note = message or "; ".join(notes)
        self._set_state(state.ACTIVE_STATES[candidate.transport], note)
        self._reset_degraded_retry()
        return True

    async def _confirm_system(self) -> tuple[bool, str]:
        """Flush resolver cache and re-check via systemd-resolved before claiming verified."""
        try:
            await nm.flush_caches()
        except nm.CommandError as e:
            decky.logger.warning("flush-caches failed: %s", e)
        return await health.verify(
            health.SYSTEM_RESOLVER, timeout=health.DNS_TIMEOUT, attempts=2
        )

    async def _set_link(self, device: str, v4: list[str], v6: list[str], force: bool = False) -> None:
        link_dns, _ = await nm.get_link_dns(device)
        if force or not nm.dns_matches(link_dns, v4, v6):
            await nm.apply_dns(device, v4, v6)
            decky.logger.info("DNS on %s set to %s %s (was %s)", device, v4, v6, link_dns)
        if self.device != device:
            self.device = device
            self._write_marker(device)

    async def _startup_cleanup(self) -> None:
        """Restore recorded DNS before terminating a leftover proxy the link may still need."""
        stale = self._read_marker()
        if stale:
            decky.logger.info("Cleaning up DNS left on %s by a previous run", stale)
            if await self._restore(stale):
                await self.proxy.kill_stale()
            else:
                decky.logger.error(
                    "Startup restore failed on %s; leaving leftover dnsproxy running for recovery",
                    stale,
                )
            return
        await self.proxy.kill_stale()

    async def _restore(self, device: str) -> bool:
        """Reapply the saved profile. Clears the marker only on success. Returns True if restored."""
        try:
            await nm.restore(device)
            decky.logger.info("Restored network DNS on %s", device)
        except nm.CommandError as e:
            decky.logger.error("Restoring %s failed: %s", device, e)
            return False
        if self.device == device:
            self.device = None
        self._clear_marker()
        self._clear_selection()
        return True

    async def _restore_with_retries(self, device: str) -> bool:
        """Try restore immediately, after 1s, and after 3s (unload/shutdown path)."""
        for attempt, delay in enumerate(RESTORE_RETRY_DELAYS):
            if delay:
                await asyncio.sleep(delay)
            if await self._restore(device):
                return True
            decky.logger.warning("Restore attempt %s/%s failed for %s",
                                 attempt + 1, len(RESTORE_RETRY_DELAYS), device)
        return False

    def _forget(self) -> None:
        """Device is confirmed inactive; runtime DNS is already gone."""
        self.device = None
        self._clear_marker()
        self._clear_selection()

    def _clear_selection(self) -> None:
        self.active_provider = None
        self.observed_transport = None
        self.verification = None
        self.verification_at = None

    def _bump_generation(self, reason: str) -> None:
        self.generation += 1
        decky.logger.info("Generation %s (%s)", self.generation, reason)

    def _generation_ok(self, gen: int, where: str) -> bool:
        if self.stopping or gen != self.generation:
            decky.logger.info("Discarding stale work at %s (gen %s, now %s)", where, gen, self.generation)
            return False
        return True

    def _health_cache_stale(self) -> bool:
        if self.state not in (state.ACTIVE_ENCRYPTED, state.ACTIVE_PLAIN):
            return False
        if self.verification_at is None:
            return True
        return (time.time() - self.verification_at) >= HEALTH_CACHE_SECONDS

    def _spawn_health_refresh(self) -> None:
        self._health_refreshing = True
        task = asyncio.create_task(self._health_refresh_and_emit())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _health_refresh_and_emit(self) -> None:
        try:
            async with self.lock:
                await self._refresh_established_health()
            await self._emit_status()
        except Exception:
            decky.logger.exception("Health refresh failed")
        finally:
            self._health_refreshing = False

    async def _refresh_established_health(self) -> None:
        """Panel-open path: re-check the sticky provider with hysteresis; full reselect only after two failures."""
        if self.state not in (state.ACTIVE_ENCRYPTED, state.ACTIVE_PLAIN):
            return
        if not self.active_provider or not self.device:
            return
        if not self._health_cache_stale():
            return
        gen = self.generation
        candidates = select.sticky_first(
            providers.candidate_order(
                self.settings.mode, self.settings.provider, self.settings.custom_servers
            ),
            self.active_provider,
            self.observed_transport,
        )
        notes: list[str] = []
        if await self._keep_established_with_hysteresis(self.device, candidates, gen, notes):
            return
        if self._generation_ok(gen, "health refresh → reselect"):
            await self._apply(self.device)

    async def _keep_established_with_hysteresis(
        self,
        device: str,
        candidates: list[providers.Candidate],
        gen: int,
        notes: list[str],
    ) -> bool:
        """If a working provider is established, keep it unless two checks ~1s apart both fail."""
        if not self.active_provider or self.verification not in (select.VERIFIED, select.DNS_ONLY):
            return False
        if self.device is not None and self.device != device:
            return False
        sticky = next(
            (
                c for c in candidates
                if c.provider_id == self.active_provider and c.transport == self.observed_transport
            ),
            None,
        )
        if sticky is None:
            return False

        async def one_check() -> tuple[str, str, list[str], list[str]]:
            if sticky.transport == providers.ENCRYPTED:
                return await self._evaluate_encrypted(sticky)
            return await self._evaluate_plain(sticky)

        first = await one_check()
        if not self._generation_ok(gen, "hysteresis first check"):
            return True  # abort apply; stale
        outcome, detail, v4, v6 = first
        if outcome in (select.VERIFIED, select.DNS_ONLY):
            # Still good: refresh timestamp; re-commit only if link needs repair.
            same = (
                self.active_provider == sticky.provider_id
                and self.observed_transport == sticky.transport
                and self.device == device
            )
            if same and not self.force_link and not self.proxy_stale:
                self.verification = outcome
                self.verification_at = time.time()
                decky.logger.info("Established %s still healthy", providers.candidate_label(sticky))
                return True
            await self._commit_candidate(
                device, sticky, v4, v6, outcome, notes,
                message=select.DNS_ONLY_MESSAGE if outcome == select.DNS_ONLY else "",
                gen=gen,
            )
            return True

        decky.logger.warning(
            "Established %s failed once (%s); rechecking in %ss",
            providers.candidate_label(sticky), detail, HYSTERESIS_SECONDS,
        )
        await asyncio.sleep(HYSTERESIS_SECONDS)
        if not self._generation_ok(gen, "hysteresis gap"):
            return True

        second = await one_check()
        if not self._generation_ok(gen, "hysteresis second check"):
            return True
        outcome, detail, v4, v6 = second
        if outcome in (select.VERIFIED, select.DNS_ONLY):
            await self._commit_candidate(
                device, sticky, v4, v6, outcome, notes,
                message=select.DNS_ONLY_MESSAGE if outcome == select.DNS_ONLY else "",
                gen=gen,
            )
            return True

        decky.logger.warning(
            "Established %s failed twice; allowing provider replacement (%s)",
            providers.candidate_label(sticky), detail,
        )
        return False

    def _cancel_degraded_retry(self) -> None:
        if self.retry_timer:
            self.retry_timer.cancel()
            self.retry_timer = None

    def _reset_degraded_retry(self) -> None:
        self._cancel_degraded_retry()
        self.retry_index = 0

    def _schedule_degraded_retry(self) -> None:
        """Retry fallback/error after 30s, 2m, then every 5m. Cancelled on disable/disconnect/portal/shutdown."""
        if self.stopping or not self.settings.enabled:
            return
        self._cancel_degraded_retry()
        delay = DEGRADED_RETRY_DELAYS[min(self.retry_index, len(DEGRADED_RETRY_DELAYS) - 1)]
        self.retry_index += 1
        decky.logger.info("Scheduling degraded retry in %ss (attempt index %s)", delay, self.retry_index)
        self.retry_timer = self.loop.call_later(delay, self._spawn_reconcile)

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
            "proxy_running": self.proxy.running,
            "active_provider": self.active_provider,
            "observed_transport": self.observed_transport,
            "verification": self.verification,
            "verification_at": self.verification_at,
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
