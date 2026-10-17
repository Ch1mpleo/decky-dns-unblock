import json
import os
import tempfile
import unittest

from dns_unblock import providers
from dns_unblock.settings import Settings


class ProviderTests(unittest.TestCase):
    def test_split_servers(self):
        self.assertEqual(
            providers.split_servers(["1.1.1.1", " 2606:4700:4700::1111 ", "1.1.1.1"]),
            (["1.1.1.1"], ["2606:4700:4700::1111"]),
        )

    def test_rejects_bad_servers(self):
        for bad in (["nope"], ["127.0.0.1"], ["0.0.0.0"], []):
            with self.assertRaises(ValueError):
                providers.split_servers(bad)

    def test_plain_servers(self):
        self.assertEqual(providers.plain_servers("quad9", []), (["9.9.9.9", "149.112.112.112"], ["2620:fe::fe", "2620:fe::9"]))
        self.assertEqual(providers.plain_servers("custom", ["192.168.1.53"]), (["192.168.1.53"], []))
        with self.assertRaises(ValueError):
            providers.plain_servers(providers.AUTOMATIC, [])

    def test_doh_upstreams_empty_for_automatic_and_custom(self):
        self.assertEqual(providers.doh_upstreams(providers.AUTOMATIC), [])
        self.assertEqual(providers.doh_upstreams(providers.CUSTOM), [])
        self.assertTrue(providers.doh_upstreams("google"))


class CandidateOrderTests(unittest.TestCase):
    def ids(self, mode, provider, custom=None):
        return [(c.provider_id, c.transport) for c in providers.candidate_order(mode, provider, custom)]

    def test_automatic_auto_mode(self):
        self.assertEqual(self.ids("auto", providers.AUTOMATIC), [
            ("cloudflare", "encrypted"), ("google", "encrypted"), ("quad9", "encrypted"),
            ("cloudflare", "plain"), ("google", "plain"), ("quad9", "plain"),
        ])

    def test_automatic_encrypted_and_plain_modes(self):
        self.assertEqual(self.ids("encrypted", providers.AUTOMATIC), [
            ("cloudflare", "encrypted"), ("google", "encrypted"), ("quad9", "encrypted"),
        ])
        self.assertEqual(self.ids("plain", providers.AUTOMATIC), [
            ("cloudflare", "plain"), ("google", "plain"), ("quad9", "plain"),
        ])

    def test_explicit_provider_stays_fixed(self):
        self.assertEqual(self.ids("auto", "google"), [
            ("google", "encrypted"), ("google", "plain"),
        ])
        self.assertEqual(self.ids("encrypted", "cloudflare"), [("cloudflare", "encrypted")])
        self.assertEqual(self.ids("plain", "quad9"), [("quad9", "plain")])

    def test_custom_plain_only(self):
        self.assertEqual(self.ids("auto", "custom", ["1.1.1.1"]), [("custom", "plain")])
        self.assertEqual(self.ids("plain", "custom", ["1.1.1.1"]), [("custom", "plain")])
        self.assertEqual(self.ids("encrypted", "custom", ["1.1.1.1"]), [])

    def test_candidate_carries_servers(self):
        enc, plain = providers.candidate_order("auto", "cloudflare")
        self.assertEqual(enc.doh[0], "https://1.1.1.1/dns-query")
        self.assertEqual(plain.v4[0], "1.1.1.1")
        custom = providers.candidate_order("plain", "custom", ["8.8.8.8", "2001:4860:4860::8888"])[0]
        self.assertEqual((custom.v4, custom.v6), (("8.8.8.8",), ("2001:4860:4860::8888",)))


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "sub", "settings.json")

    def tearDown(self):
        self.dir.cleanup()

    def write(self, data):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(data if isinstance(data, str) else json.dumps(data))

    def test_defaults_when_missing_or_corrupt(self):
        self.assertEqual(Settings(self.path).to_dict()["provider"], providers.AUTOMATIC)
        self.assertFalse(Settings(self.path).enabled)
        self.write("{not json")
        self.assertEqual(Settings(self.path).provider, providers.AUTOMATIC)

    def test_upgrade_preserves_saved_cloudflare(self):
        """0.1.0 installs that saved cloudflare keep it; not remapped to automatic."""
        self.write({"enabled": True, "mode": "auto", "provider": "cloudflare", "custom_servers": []})
        s = Settings(self.path)
        self.assertEqual(s.provider, "cloudflare")
        self.assertTrue(s.enabled)

    def test_upgrade_preserves_google_and_custom(self):
        self.write({"provider": "google", "custom_servers": []})
        self.assertEqual(Settings(self.path).provider, "google")
        self.write({"provider": "custom", "custom_servers": ["9.9.9.9"]})
        self.assertEqual(Settings(self.path).to_dict()["custom_servers"], ["9.9.9.9"])

    def test_round_trip_automatic(self):
        s = Settings(self.path)
        s.enabled = True
        s.set_provider(providers.AUTOMATIC)
        s.save()
        self.assertEqual(Settings(self.path).to_dict(), {
            "enabled": True, "mode": "auto", "provider": "automatic", "custom_servers": [],
        })

    def test_round_trip_custom(self):
        s = Settings(self.path)
        s.enabled = True
        s.set_mode("plain")
        s.set_provider("custom", ["9.9.9.9", ""])
        s.save()
        self.assertEqual(Settings(self.path).to_dict(), {
            "enabled": True, "mode": "plain", "provider": "custom", "custom_servers": ["9.9.9.9"],
        })

    def test_invalid_values_fall_back(self):
        self.write({"enabled": "yes", "mode": "turbo", "provider": "custom", "custom_servers": ["bad"]})
        s = Settings(self.path)
        self.assertEqual((s.enabled, s.mode, s.provider), (False, "auto", providers.AUTOMATIC))

    def test_setters_validate(self):
        s = Settings(self.path)
        with self.assertRaises(ValueError):
            s.set_mode("turbo")
        with self.assertRaises(ValueError):
            s.set_provider("opendns")
        with self.assertRaises(ValueError):
            s.set_provider("custom", ["not-an-ip"])
        self.assertEqual(s.provider, providers.AUTOMATIC)
        s.set_provider(providers.AUTOMATIC)
        self.assertEqual(s.provider, providers.AUTOMATIC)


if __name__ == "__main__":
    unittest.main()
