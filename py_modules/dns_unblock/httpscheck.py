"""HTTPS reachability against a candidate-resolved address (SNI + Host = hostname).

Connects to the IP directly so the check does not use the system DNS. Stdlib only.
"""

from __future__ import annotations

import asyncio
import ipaddress
import os
import socket
import ssl
from dataclasses import dataclass

from .dnsquery import SYSTEM_CA_FILE

HTTPS_TIMEOUT = 5.0
# Enough for status line + headers; we do not need the full body.
MAX_READ = 8192

REACHABLE = "reachable"
HTTP_ERROR = "http_error"
CONNECTION_FAILED = "connection_failed"


@dataclass
class HttpsResult:
    hostname: str
    address: str
    outcome: str
    detail: str
    status_code: int | None = None

    @property
    def ok(self) -> bool:
        return self.outcome == REACHABLE


def _ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=SYSTEM_CA_FILE if os.path.isfile(SYSTEM_CA_FILE) else None)


def https_get(hostname: str, address: str, timeout: float = HTTPS_TIMEOUT, path: str = "/") -> HttpsResult:
    """Unauthenticated GET to `address` with TLS SNI and HTTP Host set to `hostname`."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return HttpsResult(hostname, address, CONNECTION_FAILED, f"bad address {address!r}")

    family = socket.AF_INET6 if ip.version == 6 else socket.AF_INET
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {hostname}\r\n"
        "Connection: close\r\n"
        "User-Agent: decky-dns-unblock\r\n"
        "Accept: */*\r\n"
        "\r\n"
    ).encode()

    try:
        with socket.socket(family, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect((address, 443))
            with _ssl_context().wrap_socket(sock, server_hostname=hostname) as tls:
                tls.settimeout(timeout)
                tls.sendall(request)
                chunks: list[bytes] = []
                remaining = MAX_READ
                while remaining > 0:
                    data = tls.recv(min(4096, remaining))
                    if not data:
                        break
                    chunks.append(data)
                    remaining -= len(data)
    except ssl.SSLCertVerificationError as e:
        return HttpsResult(hostname, address, CONNECTION_FAILED, f"TLS: {e}")
    except ssl.SSLError as e:
        return HttpsResult(hostname, address, CONNECTION_FAILED, f"TLS: {e}")
    except (socket.timeout, TimeoutError):
        return HttpsResult(hostname, address, CONNECTION_FAILED, "timeout")
    except OSError as e:
        return HttpsResult(hostname, address, CONNECTION_FAILED, str(e) or type(e).__name__)

    raw = b"".join(chunks)
    if not raw:
        return HttpsResult(hostname, address, CONNECTION_FAILED, "empty response")
    try:
        status_line = raw.split(b"\r\n", 1)[0].decode("latin-1", errors="replace")
        # HTTP/1.1 200 OK
        parts = status_line.split()
        code = int(parts[1]) if len(parts) >= 2 else None
    except (ValueError, IndexError):
        return HttpsResult(hostname, address, CONNECTION_FAILED, f"bad status: {raw[:80]!r}")

    if code is None:
        return HttpsResult(hostname, address, CONNECTION_FAILED, status_line)
    if 200 <= code < 400:
        return HttpsResult(hostname, address, REACHABLE, f"HTTP {code}", status_code=code)
    return HttpsResult(hostname, address, HTTP_ERROR, f"HTTP {code}", status_code=code)


async def ahttps_get(hostname: str, address: str, timeout: float = HTTPS_TIMEOUT, path: str = "/") -> HttpsResult:
    return await asyncio.to_thread(https_get, hostname, address, timeout, path)


async def check_hostname(
    hostname: str,
    addresses: list[str],
    timeout: float = HTTPS_TIMEOUT,
) -> HttpsResult:
    """Try addresses in order (IPv4 preferred, then IPv6). First REACHABLE wins; else last failure."""
    if not addresses:
        return HttpsResult(hostname, "", CONNECTION_FAILED, "no addresses")

    def key(addr: str) -> tuple[int, str]:
        try:
            return (0 if ipaddress.ip_address(addr).version == 4 else 1, addr)
        except ValueError:
            return (2, addr)

    ordered = sorted(addresses, key=key)
    last = HttpsResult(hostname, ordered[0], CONNECTION_FAILED, "no attempt")
    for address in ordered:
        last = await ahttps_get(hostname, address, timeout=timeout)
        if last.ok:
            return last
        # Prefer reporting connection failure over HTTP error only if we never connected;
        # keep trying other addresses on connection failure; stop on HTTP error (host reached).
        if last.outcome == HTTP_ERROR:
            return last
    return last
