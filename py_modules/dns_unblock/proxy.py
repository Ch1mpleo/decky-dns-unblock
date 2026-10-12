"""Runs the bundled AdGuard dnsproxy as a local DoH forwarder on 127.0.0.2:53.

The process is awaited rather than polled: an unexpected exit calls `on_exit`. Its PID is written to a file so a
proxy left behind by a crashed plugin can be killed on the next start.
"""

import asyncio
import logging
import os
import signal
import stat
from typing import Callable

from . import nm

LISTEN_ADDR = "127.0.0.2"
LISTEN_PORT = 53
STOP_TIMEOUT = 3.0


def build_args(binary: str, upstreams: list[str]) -> list[str]:
    args = [binary, "-l", LISTEN_ADDR, "-p", str(LISTEN_PORT)]
    for upstream in upstreams:
        args += ["-u", upstream]
    return args + ["--upstream-mode", "parallel", "--cache"]


class Proxy:
    def __init__(self, binary: str, pid_path: str, log_path: str, logger: logging.Logger,
                 on_exit: Callable[[int], None]):
        self.binary = binary
        self.pid_path = pid_path
        self.log_path = log_path
        self.logger = logger
        self.on_exit = on_exit
        self.proc: asyncio.subprocess.Process | None = None
        self.upstreams: list[str] = []
        self.waiter: asyncio.Task | None = None

    @property
    def available(self) -> bool:
        return os.path.isfile(self.binary)

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    async def start(self, upstreams: list[str]) -> bool:
        """Start, or restart with new upstreams. Returns False if it was already running with them.
        Raises OSError if the binary can't be run."""
        if self.running and upstreams == self.upstreams:
            return False
        await self.stop()
        mode = os.stat(self.binary).st_mode
        if not mode & stat.S_IXUSR:
            # Zips installed through Decky can lose the executable bit.
            os.chmod(self.binary, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        with open(self.log_path, "w", encoding="utf-8") as log:
            self.proc = await asyncio.create_subprocess_exec(
                *build_args(self.binary, upstreams), stdin=asyncio.subprocess.DEVNULL,
                stdout=log, stderr=log, env=nm.command_env(),
            )
        self.upstreams = list(upstreams)
        self._write_pid(self.proc.pid)
        self.waiter = asyncio.create_task(self._wait(self.proc))
        self.logger.info("dnsproxy started (pid %s): %s", self.proc.pid, upstreams)
        return True

    async def stop(self) -> None:
        proc, self.proc = self.proc, None
        if self.waiter:
            self.waiter.cancel()
            self.waiter = None
        if proc and proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), STOP_TIMEOUT)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
            self.logger.info("dnsproxy stopped")
        self._clear_pid()

    async def _wait(self, proc: asyncio.subprocess.Process) -> None:
        code = await proc.wait()
        if self.proc is proc:
            self.proc = None
            self._clear_pid()
            self.logger.warning("dnsproxy exited unexpectedly (code %s), see %s", code, self.log_path)
            self.on_exit(code)

    async def kill_stale(self) -> None:
        """Kill a dnsproxy recorded by a previous run that didn't shut down cleanly."""
        try:
            with open(self.pid_path, encoding="utf-8") as f:
                pid = int(f.read().strip())
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                cmdline = f.read()
        except (OSError, ValueError):
            self._clear_pid()
            return
        if b"dnsproxy" in cmdline:
            self.logger.info("Killing dnsproxy left by a previous run (pid %s)", pid)
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError as e:
                self.logger.warning("Could not kill pid %s: %s", pid, e)
            # Wait for it to release port 53 before a new proxy tries to bind it.
            for _ in range(20):
                if not os.path.exists(f"/proc/{pid}"):
                    break
                await asyncio.sleep(0.1)
        self._clear_pid()

    def _write_pid(self, pid: int) -> None:
        try:
            os.makedirs(os.path.dirname(self.pid_path), exist_ok=True)
            with open(self.pid_path, "w", encoding="utf-8") as f:
                f.write(str(pid))
        except OSError as e:
            self.logger.warning("Could not write %s: %s", self.pid_path, e)

    def _clear_pid(self) -> None:
        try:
            os.remove(self.pid_path)
        except OSError:
            pass
