"""What the plugin should be doing, decided from the current network facts (pure, unit-tested).

The backend re-reads the facts after every NetworkManager event and calls `decide`, so a missed or reordered
event can't leave it out of sync.
"""

from dataclasses import dataclass

# States reported to the frontend.
OFF = "off"
NO_NETWORK = "no_network"
WAITING = "waiting"
PAUSED = "paused"
ACTIVE_PLAIN = "active_plain"
ERROR = "error"

# Actions for the backend.
APPLY = "apply"      # put our DNS on the device (no-op if it's already there)
RESTORE = "restore"  # give the device back the network's own DNS
FORGET = "forget"    # the device went down, which already dropped our runtime DNS
KEEP = "keep"        # change nothing for now

# How long to wait after connecting for NetworkManager's internet check before applying anyway.
SETTLE_SECONDS = 10.0


@dataclass(frozen=True)
class Decision:
    state: str
    action: str
    message: str = ""


def decide(enabled: bool, device: str | None, connectivity: str, settled: bool, applied: bool) -> Decision:
    """
    enabled:      the user's toggle
    device:       connected Wi-Fi device, or None
    connectivity: NetworkManager's internet check (full / portal / limited / none / unknown)
    settled:      SETTLE_SECONDS have passed since the device connected
    applied:      our DNS is already on this device (and it hasn't reconnected since)
    """
    if not enabled:
        return Decision(OFF, RESTORE)
    if device is None:
        return Decision(NO_NETWORK, FORGET, "No connected Wi-Fi")
    if connectivity == "portal":
        return Decision(PAUSED, RESTORE, "Wi-Fi sign-in page detected, using the network's DNS until you log in")
    # Once our DNS is on, a flaky internet check is no reason to take it off again.
    if connectivity == "full" or applied or settled:
        return Decision(ACTIVE_PLAIN, APPLY)
    return Decision(WAITING, KEEP, "Waiting for the internet check")
