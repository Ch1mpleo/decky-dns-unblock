"""Long-lived `nmcli monitor` reader that turns NetworkManager output into events.

Nothing is polled: the reader just awaits the next line. If nmcli exits, it is restarted with a growing delay,
and a STARTED event tells the owner to resync since events may have been missed.
Line formats are documented in docs/spike-notes.md (section 5).
"""

import asyncio
import logging
import re
import time
from typing import Callable, NamedTuple

from . import nm

DEVICE_UP = "device_up"
DEVICE_DOWN = "device_down"
CONNECTIVITY = "connectivity"
NM_STATE = "nm_state"
STARTED = "started"

_DEVICE = re.compile(r"^(\S+): (connected|disconnected|unavailable|unmanaged|deactivating)$")
_CONNECTIVITY = re.compile(r"^Connectivity is now '(\w+)'$")
_NM_STATE = re.compile(r"^Networkmanager is now in the '(.*)' state$")

RESTART_DELAYS = (1, 2, 5, 15, 30, 60)
# A monitor that ran this long counts as healthy, so the next restart starts from the shortest delay again.
HEALTHY_SECONDS = 60


class Event(NamedTuple):
    kind: str
    value: str = ""


def parse_line(line: str) -> Event | None:
    """Map one `nmcli monitor` line to an event; everything else (profile churn, activation steps) is None."""
    line = line.strip()
    m = _DEVICE.match(line)
    if m:
        return Event(DEVICE_UP if m.group(2) == "connected" else DEVICE_DOWN, m.group(1))
    m = _CONNECTIVITY.match(line)
    if m:
        return Event(CONNECTIVITY, m.group(1))
    m = _NM_STATE.match(line)
    if m:
        return Event(NM_STATE, m.group(1))
    return None


class Watcher:
    def __init__(self, on_event: Callable[[Event], None], logger: logging.Logger,
                 command: tuple[str, ...] = (nm.NMCLI, "monitor")):
        self.on_event = on_event
        self.logger = logger
        self.command = command
        self.task: asyncio.Task | None = None
        self.proc: asyncio.subprocess.Process | None = None

    def start(self) -> None:
        if self.task is None:
            self.task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self.task is None:
            return
        self.task.cancel()
        try:
            await self.task
        except asyncio.CancelledError:
            pass
        self.task = None

    async def _run(self) -> None:
        failures = 0
        while True:
            started = time.monotonic()
            try:
                await self._read_once()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # keep watching whatever goes wrong with one nmcli run
                self.logger.error("nmcli monitor failed: %s", e)
            if time.monotonic() - started >= HEALTHY_SECONDS:
                failures = 0
            delay = RESTART_DELAYS[min(failures, len(RESTART_DELAYS) - 1)]
            failures += 1
            self.logger.warning("nmcli monitor stopped, restarting in %ss", delay)
            await asyncio.sleep(delay)

    async def _read_once(self) -> None:
        self.proc = await asyncio.create_subprocess_exec(
            *self.command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            env=nm.command_env(),
        )
        try:
            self.on_event(Event(STARTED))
            assert self.proc.stdout is not None
            while True:
                raw = await self.proc.stdout.readline()
                if not raw:
                    break
                event = parse_line(raw.decode(errors="replace"))
                if event:
                    self.on_event(event)
        finally:
            if self.proc.returncode is None:
                self.proc.kill()
            await self.proc.wait()
            self.proc = None
