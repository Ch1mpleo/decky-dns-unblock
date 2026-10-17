import unittest

from dns_unblock import providers, select


class SelectHelperTests(unittest.TestCase):
    def test_sticky_first_prefers_active(self):
        candidates = providers.candidate_order("auto", providers.AUTOMATIC)
        ordered = select.sticky_first(candidates, "google", providers.ENCRYPTED)
        self.assertEqual(ordered[0].provider_id, "google")
        self.assertEqual(ordered[0].transport, providers.ENCRYPTED)
        self.assertEqual(len(ordered), len(candidates))

    def test_sticky_first_noop_when_missing(self):
        candidates = providers.candidate_order("auto", "cloudflare")
        self.assertEqual(select.sticky_first(candidates, None, None), candidates)
        self.assertEqual(select.sticky_first(candidates, "quad9", providers.ENCRYPTED), candidates)

    def test_active_status_label(self):
        labels = {"active_encrypted": "Active - Encrypted", "fallback": "Fallback - network DNS"}
        self.assertEqual(
            select.active_status_label("active_encrypted", "google", providers.ENCRYPTED, select.VERIFIED, labels),
            "Active · Google · Encrypted",
        )
        self.assertEqual(
            select.active_status_label("active_plain", "cloudflare", providers.PLAIN, select.DNS_ONLY, labels),
            "Active · Cloudflare · Plain (Steam unverified)",
        )
        self.assertEqual(select.active_status_label("fallback", None, "network", select.FAILED, labels),
                         "Fallback - network DNS")

    def test_dns_only_message(self):
        self.assertEqual(select.DNS_ONLY_MESSAGE, "DNS working; Steam access unverified.")


if __name__ == "__main__":
    unittest.main()
