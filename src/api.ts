import { callable } from "@decky/api";

export type Mode = "auto" | "encrypted" | "plain";

export type Verification = "verified" | "dns_only" | "failed" | null;
export type ObservedTransport = "encrypted" | "plain" | "network" | null;

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
  proxy_running: boolean;
  /** Provider actually in use (may differ from preference when Automatic). */
  active_provider: string | null;
  observed_transport: ObservedTransport;
  verification: Verification;
  verification_at: number | null;
};

export const PROXY_ADDR = "127.0.0.2";

export type DnsVerdict =
  | "resolved"
  | "lookup_failed"
  | "possible_dns_blocking"
  | "unknown"
  | "ok"
  | "blocked";

export type HttpsVerdict = "reachable" | "http_error" | "connection_failed" | "unknown";

export type DnsCell = { verdict: DnsVerdict; detail: string; addresses?: string[] };
export type HttpsCell = { verdict: HttpsVerdict; detail: string; status_code?: number | null };

export type DiagnosticsContext = {
  mode: Mode | string;
  provider: string;
  active_provider: string | null;
  device: string | null;
};

export type Diagnostics = {
  timestamp: number;
  mode: Mode | string;
  provider: string;
  active_provider: string | null;
  connectivity: string;
  device: string | null;
  network_dns: string[];
  resolver: string;
  rows: {
    domain: string;
    network: DnsCell;
    provider: DnsCell;
    system: DnsCell;
    https: HttpsCell;
  }[];
  summary: string;
  context: DiagnosticsContext;
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
  { data: "auto", label: "Auto" },
  { data: "encrypted", label: "Encrypted only" },
  { data: "plain", label: "Plain only" },
];

export const PROVIDER_OPTIONS = [
  { data: "automatic", label: "Automatic" },
  { data: "cloudflare", label: "Cloudflare" },
  { data: "google", label: "Google" },
  { data: "quad9", label: "Quad9" },
  { data: "custom", label: "Custom" },
];

export const labelOf = (options: { data: string; label: string }[], value: string) =>
  options.find((o) => o.data === value)?.label ?? value;

const SHORT_PROVIDER: Record<string, string> = {
  automatic: "Automatic",
  cloudflare: "Cloudflare",
  google: "Google",
  quad9: "Quad9",
  custom: "Custom",
};

const transportName = (t: ObservedTransport) =>
  t === "encrypted" ? "Encrypted" : t === "plain" ? "Plain" : t === "network" ? "Network DNS" : "—";

/** Concise status, e.g. "Active · Google · Encrypted". Extra detail stays in Note. */
export const statusLabel = (status: Status) => {
  if (status.state === "active_encrypted" || status.state === "active_plain") {
    const active = status.active_provider ?? status.provider;
    const transport = status.observed_transport
      ?? (status.state === "active_encrypted" ? "encrypted" : "plain");
    const name = SHORT_PROVIDER[active] ?? labelOf(PROVIDER_OPTIONS, active);
    return `Active · ${name} · ${transportName(transport)}`;
  }
  return STATE_LABELS[status.state] ?? status.state;
};

/** Fingerprint used to invalidate sticky diagnostics when selection/network context changes. */
export const diagnosticsContextKey = (ctx: {
  mode?: string | null;
  provider?: string | null;
  active_provider?: string | null;
  device?: string | null;
}) => `${ctx.mode ?? ""}|${ctx.provider ?? ""}|${ctx.active_provider ?? ""}|${ctx.device ?? ""}`;

export const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));
