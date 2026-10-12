"""Minimal stdlib-only DNS client (UDP and DoH, A/AAAA), so the backend needs no pip packages on the Deck."""

import asyncio
import base64
import ipaddress
import json
import os
import socket
import ssl
import struct
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field

# Decky's bundled Python may not find the system CA store on its own.
SYSTEM_CA_FILE = "/etc/ssl/certs/ca-certificates.crt"

TYPE_A = 1
TYPE_AAAA = 28
TYPES = {"A": TYPE_A, "AAAA": TYPE_AAAA}

RCODE_NAMES = {0: "NOERROR", 1: "FORMERR", 2: "SERVFAIL", 3: "NXDOMAIN", 4: "NOTIMP", 5: "REFUSED"}


@dataclass
class Result:
    server: str
    name: str
    rcode: str | None = None
    addresses: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def build_query(name: str, qtype: int = TYPE_A, qid: int | None = None) -> bytes:
    if qid is None:
        qid = int.from_bytes(os.urandom(2), "big")
    header = struct.pack(">HHHHHH", qid, 0x0100, 1, 0, 0, 0)  # RD set, one question
    qname = b"".join(
        bytes([len(label)]) + label for label in (p.encode("idna") for p in name.rstrip(".").split(".")) if label
    ) + b"\x00"
    return header + qname + struct.pack(">HH", qtype, 1)


def _skip_name(data: bytes, offset: int) -> int:
    while True:
        if offset >= len(data):
            raise ValueError("truncated name")
        length = data[offset]
        if length & 0xC0 == 0xC0:
            return offset + 2
        if length == 0:
            return offset + 1
        offset += 1 + length


def parse_response(data: bytes, qid: int | None = None) -> tuple[str, list[str]]:
    """Return (rcode name, A/AAAA addresses in the answer section)."""
    if len(data) < 12:
        raise ValueError("short response")
    rid, flags, qdcount, ancount, _, _ = struct.unpack(">HHHHHH", data[:12])
    if qid is not None and rid != qid:
        raise ValueError("response id mismatch")
    rcode = flags & 0x000F
    offset = 12
    for _ in range(qdcount):
        offset = _skip_name(data, offset) + 4
    addresses = []
    for _ in range(ancount):
        offset = _skip_name(data, offset)
        rtype, _, _, rdlength = struct.unpack(">HHIH", data[offset:offset + 10])
        offset += 10
        rdata = data[offset:offset + rdlength]
        offset += rdlength
        if rtype == TYPE_A and rdlength == 4:
            addresses.append(str(ipaddress.IPv4Address(rdata)))
        elif rtype == TYPE_AAAA and rdlength == 16:
            addresses.append(str(ipaddress.IPv6Address(rdata)))
    return RCODE_NAMES.get(rcode, str(rcode)), addresses


def query(server: str, name: str, qtype: int = TYPE_A, timeout: float = 3.0, port: int = 53) -> Result:
    result = Result(server=server, name=name)
    qid = int.from_bytes(os.urandom(2), "big")
    packet = build_query(name, qtype, qid)
    family = socket.AF_INET6 if ":" in server else socket.AF_INET
    try:
        with socket.socket(family, socket.SOCK_DGRAM) as sock:
            sock.settimeout(timeout)
            # Connected, so a closed port fails fast with ConnectionRefusedError instead of a silent timeout.
            sock.connect((server, port))
            sock.send(packet)
            while True:
                data = sock.recv(4096)
                try:
                    result.rcode, result.addresses = parse_response(data, qid)
                    break
                except ValueError as e:
                    if str(e) != "response id mismatch":
                        raise
    except socket.timeout:
        result.error = "timeout"
    except (OSError, ValueError, struct.error) as e:
        result.error = str(e) or type(e).__name__
    return result


async def aquery(server: str, name: str, qtype: int = TYPE_A, timeout: float = 3.0, port: int = 53) -> Result:
    return await asyncio.to_thread(query, server, name, qtype, timeout, port)


def doh_url(url: str, name: str, qtype: int = TYPE_A) -> str:
    """RFC 8484 GET URL. ID 0 as the RFC recommends, base64url without padding."""
    packet = base64.urlsafe_b64encode(build_query(name, qtype, 0)).rstrip(b"=").decode()
    return f"{url}?dns={packet}"


def _opener() -> urllib.request.OpenerDirector:
    context = ssl.create_default_context(cafile=SYSTEM_CA_FILE if os.path.isfile(SYSTEM_CA_FILE) else None)
    # No proxies: the point is to test the direct path from this network.
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))


def doh_query(url: str, name: str, qtype: int = TYPE_A, timeout: float = 4.0) -> Result:
    result = Result(server=url, name=name)
    request = urllib.request.Request(doh_url(url, name, qtype), headers={"accept": "application/dns-message"})
    try:
        with _opener().open(request, timeout=timeout) as response:
            result.rcode, result.addresses = parse_response(response.read(65535), 0)
    except urllib.error.HTTPError as e:
        result.error = f"HTTP {e.code}"
    except urllib.error.URLError as e:
        reason = e.reason
        result.error = "timeout" if isinstance(reason, (socket.timeout, TimeoutError)) else str(reason)
    except (socket.timeout, TimeoutError):
        result.error = "timeout"
    except (OSError, ValueError, struct.error) as e:
        result.error = str(e) or type(e).__name__
    return result


async def adoh_query(url: str, name: str, qtype: int = TYPE_A, timeout: float = 4.0) -> Result:
    return await asyncio.to_thread(doh_query, url, name, qtype, timeout)


if __name__ == "__main__":
    # Usage: python3 dnsquery.py <server IP or https:// DoH URL> <name> [A|AAAA]
    srv, host = sys.argv[1], sys.argv[2]
    qt = TYPES[sys.argv[3].upper()] if len(sys.argv) > 3 else TYPE_A
    res = doh_query(srv, host, qt) if srv.startswith("https://") else query(srv, host, qt)
    print(json.dumps(res.to_dict()))
