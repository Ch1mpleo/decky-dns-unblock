"""Persistent plugin settings, stored as JSON. No decky import so it can be unit-tested anywhere."""

import json
import os

from . import providers

MODES = ("auto", "encrypted", "plain")
DEFAULTS = {
    "enabled": False,
    "mode": "auto",
    "provider": "cloudflare",
    "custom_servers": [],
}


class Settings:
    def __init__(self, path: str):
        self.path = path
        self.enabled: bool = DEFAULTS["enabled"]
        self.mode: str = DEFAULTS["mode"]
        self.provider: str = DEFAULTS["provider"]
        self.custom_servers: list[str] = list(DEFAULTS["custom_servers"])
        self.load()

    def load(self) -> None:
        """Load from disk; unknown keys and invalid values fall back to defaults."""
        try:
            with open(self.path, encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, ValueError):
            return
        if not isinstance(raw, dict):
            return
        if isinstance(raw.get("enabled"), bool):
            self.enabled = raw["enabled"]
        if raw.get("mode") in MODES:
            self.mode = raw["mode"]
        servers = raw.get("custom_servers")
        if isinstance(servers, list) and all(isinstance(s, str) for s in servers):
            self.custom_servers = servers
        provider = raw.get("provider")
        if provider in providers.PROVIDERS or (provider == providers.CUSTOM and self._custom_valid()):
            self.provider = provider

    def _custom_valid(self) -> bool:
        try:
            providers.split_servers(self.custom_servers)
            return True
        except ValueError:
            return False

    def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            raise ValueError(f"Unknown mode: {mode!r}")
        self.mode = mode

    def set_provider(self, provider: str, custom_servers: list[str] | None = None) -> None:
        if provider == providers.CUSTOM:
            servers = [s.strip() for s in (custom_servers or []) if s.strip()]
            providers.split_servers(servers)
            self.custom_servers = servers
        elif provider not in providers.PROVIDERS:
            raise ValueError(f"Unknown provider: {provider!r}")
        self.provider = provider

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "mode": self.mode,
            "provider": self.provider,
            "custom_servers": list(self.custom_servers),
        }

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)
        os.replace(tmp, self.path)
