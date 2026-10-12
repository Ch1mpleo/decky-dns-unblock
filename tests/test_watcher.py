import asyncio
import logging
import sys
import unittest

from dns_unblock import watcher
from dns_unblock.watcher import Event, parse_line

# Lines recorded on the Deck, see docs/spike-notes.md section 5.
SAMPLES = {
    "wlan0: connected": Event(watcher.DEVICE_UP, "wlan0"),
    "wlan0: disconnected": Event(watcher.DEVICE_DOWN, "wlan0"),
    "wlan0: unavailable": Event(watcher.DEVICE_DOWN, "wlan0"),
    "wlan0: unmanaged": Event(watcher.DEVICE_DOWN, "wlan0"),
    "wlan0: deactivating": Event(watcher.DEVICE_DOWN, "wlan0"),
    "Connectivity is now 'full'": Event(watcher.CONNECTIVITY, "full"),
    "Connectivity is now 'portal'": Event(watcher.CONNECTIVITY, "portal"),
    "Networkmanager is now in the 'asleep' state": Event(watcher.NM_STATE, "asleep"),
    "Networkmanager is now in the 'connected (site only)' state": Event(watcher.NM_STATE, "connected (site only)"),
}
IGNORED = [
    "wlan0: using connection 'HuuTam_A3_5G'",
    "wlan0: connecting (getting IP configuration)",
    "'HuuTam_A3_5G' is now the primary connection",
    "There's no primary connection",
    "HuuTam_A3_5G: connection profile changed",
    "Nothing phone (Ch1mple): connection profile created",
    "",
]


class ParseLineTests(unittest.TestCase):
    def test_events(self):
        for line, event in SAMPLES.items():
            self.assertEqual(parse_line(line + "\n"), event, line)

    def test_ignored(self):
        for line in IGNORED:
            self.assertIsNone(parse_line(line), line)


class WatcherTests(unittest.IsolatedAsyncioTestCase):
    async def test_reads_lines_and_restarts(self):
        script = "print('wlan0: connected', flush=True); print(\"Connectivity is now 'full'\", flush=True)"
        events: list[Event] = []
        done = asyncio.Event()

        def on_event(event: Event) -> None:
            events.append(event)
            if events.count(Event(watcher.STARTED)) == 2:
                done.set()

        w = watcher.Watcher(on_event, logging.getLogger("test"), command=(sys.executable, "-c", script))
        w.start()
        await asyncio.wait_for(done.wait(), timeout=20)
        await w.stop()
        self.assertEqual(events[:4], [
            Event(watcher.STARTED),
            Event(watcher.DEVICE_UP, "wlan0"),
            Event(watcher.CONNECTIVITY, "full"),
            Event(watcher.STARTED),
        ])
        self.assertIsNone(w.task)


if __name__ == "__main__":
    unittest.main()
