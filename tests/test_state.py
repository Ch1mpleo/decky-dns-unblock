import unittest

from dns_unblock import state
from dns_unblock.state import decide


def run(enabled=True, device="wlan0", connectivity="full", settled=False, applied=False):
    return decide(enabled=enabled, device=device, connectivity=connectivity, settled=settled, applied=applied)


class DecideTests(unittest.TestCase):
    def test_disabled_restores(self):
        self.assertEqual((run(enabled=False).state, run(enabled=False).action), (state.OFF, state.RESTORE))

    def test_no_device_forgets(self):
        d = run(device=None, connectivity="none")
        self.assertEqual((d.state, d.action), (state.NO_NETWORK, state.FORGET))

    def test_full_applies(self):
        d = run(connectivity="full")
        self.assertEqual((d.state, d.action), (state.ACTIVE_PLAIN, state.APPLY))

    def test_portal_pauses_even_when_applied(self):
        d = run(connectivity="portal", applied=True, settled=True)
        self.assertEqual((d.state, d.action), (state.PAUSED, state.RESTORE))

    def test_waits_for_connectivity_after_connecting(self):
        for connectivity in ("none", "limited", "unknown"):
            d = run(connectivity=connectivity)
            self.assertEqual((d.state, d.action), (state.WAITING, state.KEEP), connectivity)

    def test_applies_anyway_once_settled(self):
        d = run(connectivity="limited", settled=True)
        self.assertEqual((d.state, d.action), (state.ACTIVE_PLAIN, state.APPLY))

    def test_flaky_check_keeps_applied_dns(self):
        d = run(connectivity="limited", applied=True)
        self.assertEqual((d.state, d.action), (state.ACTIVE_PLAIN, state.APPLY))


if __name__ == "__main__":
    unittest.main()
