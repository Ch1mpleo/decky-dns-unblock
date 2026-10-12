"""Minimal stdlib-only DNS client (UDP, A/AAAA), so the backend needs no pip packages on the Deck."""

import asyncio
import ipaddress
import json
import os
import socket
import struct
import sys
from dataclasses import asdict, dataclass, field

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
            sock.sendto(packet, (server, port))
            while True:
                data, _ = sock.recvfrom(4096)
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


if __name__ == "__main__":
    # Usage: python3 dnsquery.py <server> <name> [A|AAAA]
    srv, host = sys.argv[1], sys.argv[2]
    qt = TYPES[sys.argv[3].upper()] if len(sys.argv) > 3 else TYPE_A
    print(json.dumps(query(srv, host, qt).to_dict()))
