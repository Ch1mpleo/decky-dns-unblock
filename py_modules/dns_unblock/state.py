"""What the plugin should be doing, decided from the current network facts (pure, unit-tested).

The backend re-reads the facts after every NetworkManager event and calls `decide`, so a missed or reordered
event can't leave it out of sync. When the answer is "turn our DNS on", `attempts` lists what to try, in order.
"""

from dataclasses import dataclass

# States reported to the frontend.
OFF = "off"
NO_NETWORK = "no_network"
WAITING = "waiting"
PAUSED = "paused"
ACTIVE = "active"  # placeholder from `decide`; the apply chain turns it into one of the three below
ACTIVE_ENCRYPTED = "active_encrypted"
ACTIVE_PLAIN = "active_plain"
FALLBACK = "fallback"
ERROR = "error"

# Actions for the backend.
APPLY = "apply"      # run the apply chain (no-op on the device if our DNS is already there)
RESTORE = "restore"  # give the device back the network's own DNS
FORGET = "forget"    # the device went down, which already dropped our runtime DNS
KEEP = "keep"        # change nothing for now

# Apply chain steps.
ENCRYPTED = "encrypted"
PLAIN = "plain"
ACTIVE_STATES = {ENCRYPTED: ACTIVE_ENCRYPTED, PLAIN: ACTIVE_PLAIN}

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
        return Decision(ACTIVE, APPLY)
    return Decision(WAITING, KEEP, "Waiting for the internet check")


def attempts(mode: str, encrypted_available: bool) -> list[str]:
    """Steps to try for a mode; an empty list (or every step failing) means falling back to the network's DNS."""
    if mode == PLAIN:
        return [PLAIN]
    if mode == ENCRYPTED:
        return [ENCRYPTED] if encrypted_available else []
    return [ENCRYPTED, PLAIN] if encrypted_available else [PLAIN]
