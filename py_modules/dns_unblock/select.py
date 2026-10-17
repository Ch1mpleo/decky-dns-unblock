"""Status / selection helpers (pure, unit-tested)."""

from . import providers

VERIFIED = "verified"
DNS_ONLY = "dns_only"
FAILED = "failed"

DNS_ONLY_MESSAGE = "DNS working; Steam access unverified."


def provider_display_name(provider_id: str | None) -> str:
    if not provider_id:
        return "—"
    if provider_id == providers.AUTOMATIC:
        return "Automatic"
    if provider_id == providers.CUSTOM:
        return "Custom"
    preset = providers.PROVIDERS.get(provider_id)
    return preset.label if preset else provider_id


def transport_display_name(transport: str | None) -> str:
    if transport == providers.ENCRYPTED:
        return "Encrypted"
    if transport == providers.PLAIN:
        return "Plain"
    if transport == "network":
        return "Network DNS"
    return "—"


def active_status_label(
    state_name: str,
    active_provider: str | None,
    observed_transport: str | None,
    verification: str | None,
    state_labels: dict[str, str],
) -> str:
    """Concise Active line, e.g. 'Active · Google · Encrypted'."""
    if state_name in ("active_encrypted", "active_plain"):
        parts = ["Active", provider_display_name(active_provider), transport_display_name(observed_transport)]
        label = " · ".join(parts)
        if verification == DNS_ONLY:
            return f"{label} (Steam unverified)"
        return label
    return state_labels.get(state_name, state_name)


def sticky_first(
    candidates: list[providers.Candidate],
    active_provider: str | None,
    observed_transport: str | None,
) -> list[providers.Candidate]:
    """Prefer the previously selected candidate for this connection; do not invent a new one."""
    if not active_provider or not observed_transport:
        return list(candidates)
    sticky = [
        c for c in candidates
        if c.provider_id == active_provider and c.transport == observed_transport
    ]
    if not sticky:
        return list(candidates)
    rest = [c for c in candidates if c not in sticky]
    return sticky + rest
