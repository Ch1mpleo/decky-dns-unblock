"""Runs the bundled AdGuard dnsproxy as a local DoH forwarder.

The live forwarder listens on 127.0.0.2:53. Short-lived probe instances use loopback ports
15353–15355 so candidate evaluation does not disturb the active resolver.
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
PROBE_PORTS = (15353, 15354, 15355)
STOP_TIMEOUT = 3.0
PROBE_BIND_WAIT = 0.2


def build_args(
    binary: str,
    upstreams: list[str],
    listen: str = LISTEN_ADDR,
    port: int = LISTEN_PORT,
    cache: bool = True,
) -> list[str]:
    args = [binary, "-l", listen, "-p", str(port)]
    for upstream in upstreams:
        args += ["-u", upstream]
    args += ["--upstream-mode", "parallel"]
    if cache:
        args.append("--cache")
    return args


def _ensure_executable(binary: str) -> None:
    mode = os.stat(binary).st_mode
    if not mode & stat.S_IXUSR:
        # Zips installed through Decky can lose the executable bit.
        os.chmod(binary, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


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
        self.listen = LISTEN_ADDR
        self.port = LISTEN_PORT
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
        _ensure_executable(self.binary)
        with open(self.log_path, "w", encoding="utf-8") as log:
            self.proc = await asyncio.create_subprocess_exec(
                *build_args(self.binary, upstreams, self.listen, self.port),
                stdin=asyncio.subprocess.DEVNULL,
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


class ProbeProxy:
    """Isolated dnsproxy for candidate evaluation. Does not touch the live proxy PID file.

    Tries ports 15353–15355; never terminates an unrelated listener if a port is busy.
    """

    def __init__(self, binary: str, log_path: str, logger: logging.Logger, listen: str = LISTEN_ADDR):
        self.binary = binary
        self.log_path = log_path
        self.logger = logger
        self.listen = listen
        self.port: int | None = None
        self.proc: asyncio.subprocess.Process | None = None
        self.upstreams: list[str] = []

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    async def start(self, upstreams: list[str]) -> int:
        """Start on the first free probe port. Returns the bound port. Raises OSError if none work."""
        if not os.path.isfile(self.binary):
            raise OSError(f"dnsproxy not found: {self.binary}")
        _ensure_executable(self.binary)
        await self.stop()
        errors: list[str] = []
        for port in PROBE_PORTS:
            # Truncate log on first attempt only; later attempts append context.
            mode = "w" if not errors else "a"
            with open(self.log_path, mode, encoding="utf-8") as log:
                if errors:
                    log.write(f"\n# retry port {port}\n")
                self.proc = await asyncio.create_subprocess_exec(
                    *build_args(self.binary, upstreams, self.listen, port, cache=False),
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=log, stderr=log, env=nm.command_env(),
                )
            await asyncio.sleep(PROBE_BIND_WAIT)
            if self.proc.returncode is None:
                self.port = port
                self.upstreams = list(upstreams)
                self.logger.info("probe dnsproxy on %s:%s (pid %s)", self.listen, port, self.proc.pid)
                return port
            errors.append(f"port {port} exited {self.proc.returncode}")
            self.proc = None
        raise OSError("no free probe port (" + "; ".join(errors) + ")")

    async def stop(self) -> None:
        proc, self.proc = self.proc, None
        port, self.port = self.port, None
        self.upstreams = []
        if proc and proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), STOP_TIMEOUT)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
            self.logger.info("probe dnsproxy on port %s stopped", port)
