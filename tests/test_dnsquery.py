import struct
import unittest

from dns_unblock import dnsquery


def response(query: bytes, rcode: int = 0, answers: list[tuple[int, bytes]] = ()) -> bytes:
    """Build a server reply to `query`: same ID and question, answers as (type, rdata) using a name pointer."""
    qid = struct.unpack(">H", query[:2])[0]
    header = struct.pack(">HHHHHH", qid, 0x8180 | rcode, 1, len(answers), 0, 0)
    body = query[12:]
    for rtype, rdata in answers:
        body += struct.pack(">HHHIH", 0xC00C, rtype, 1, 300, len(rdata)) + rdata
    return header + body


class PacketTests(unittest.TestCase):
    def test_query_layout(self):
        q = dnsquery.build_query("store.steampowered.com", dnsquery.TYPE_A, qid=0x1234)
        self.assertEqual(q[:12], struct.pack(">HHHHHH", 0x1234, 0x0100, 1, 0, 0, 0))
        self.assertEqual(q[12:], b"\x05store\x0csteampowered\x03com\x00" + struct.pack(">HH", 1, 1))

    def test_a_answer(self):
        q = dnsquery.build_query("store.steampowered.com", qid=7)
        reply = response(q, answers=[(dnsquery.TYPE_A, bytes([23, 15, 142, 182]))])
        self.assertEqual(dnsquery.parse_response(reply, 7), ("NOERROR", ["23.15.142.182"]))

    def test_aaaa_answer_and_skips_other_types(self):
        q = dnsquery.build_query("example.com", dnsquery.TYPE_AAAA, qid=9)
        v6 = bytes.fromhex("26064700470000000000000000001111")
        reply = response(q, answers=[(5, b"\x00"), (dnsquery.TYPE_AAAA, v6)])
        self.assertEqual(dnsquery.parse_response(reply, 9), ("NOERROR", ["2606:4700:4700::1111"]))

    def test_isp_nxdomain(self):
        q = dnsquery.build_query("store.steampowered.com", qid=3)
        self.assertEqual(dnsquery.parse_response(response(q, rcode=3), 3), ("NXDOMAIN", []))

    def test_rejects_mismatched_or_short(self):
        q = dnsquery.build_query("example.com", qid=1)
        with self.assertRaises(ValueError):
            dnsquery.parse_response(response(q), 2)
        with self.assertRaises(ValueError):
            dnsquery.parse_response(b"\x00\x01")


if __name__ == "__main__":
    unittest.main()
