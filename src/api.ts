import { callable } from "@decky/api";

export type Mode = "auto" | "encrypted" | "plain";

export type Status = {
  enabled: boolean;
  mode: Mode;
  provider: string;
  custom_servers: string[];
  state: string;
  message: string;
  device: string | null;
  link_dns: string[];
  current_dns: string | null;
  connectivity: string;
};

export type Verdict = { verdict: "ok" | "blocked" | "unknown"; detail: string };

export type Diagnostics = {
  device: string | null;
  network_dns: string[];
  rows: { domain: string; network: Verdict; system: Verdict }[];
};

export const getStatus = callable<[], Status>("get_status");
export const setEnabled = callable<[enabled: boolean], Status>("set_enabled");
export const setMode = callable<[mode: Mode], Status>("set_mode");
export const setProvider = callable<[provider: string, customServers?: string[]], Status>("set_provider");
export const runDiagnostics = callable<[], Diagnostics>("run_diagnostics");

export const STATE_LABELS: Record<string, string> = {
  off: "Off",
  no_network: "No Wi-Fi connected",
  waiting: "Waiting for network",
  paused: "Paused - Wi-Fi login",
  active_encrypted: "Active - Encrypted",
  active_plain: "Active - Plain",
  fallback: "Fallback - network DNS",
  error: "Error",
};

// Backend states worth a toast even when the panel is closed.
export const NOTIFY_STATES = ["paused", "fallback", "error"];

export const MODE_OPTIONS: { data: Mode; label: string }[] = [
  { data: "auto", label: "Auto (encrypted, then plain)" },
  { data: "encrypted", label: "Encrypted only" },
  { data: "plain", label: "Plain only" },
];

export const PROVIDER_OPTIONS = [
  { data: "cloudflare", label: "Cloudflare" },
  { data: "google", label: "Google" },
  { data: "quad9", label: "Quad9" },
  { data: "custom", label: "Custom" },
];

export const labelOf = (options: { data: string; label: string }[], value: string) =>
  options.find((o) => o.data === value)?.label ?? value;

export const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));
