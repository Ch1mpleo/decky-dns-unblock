import {
  ButtonItem,
  DropdownItem,
  Field,
  PanelSection,
  PanelSectionRow,
  TextField,
  ToggleField,
  staticClasses
} from "@decky/ui";
import {
  addEventListener,
  definePlugin,
  removeEventListener,
  toaster,
} from "@decky/api"
import { Fragment, useEffect, useState } from "react";
import { FaShieldAlt } from "react-icons/fa";

import {
  Diagnostics,
  DnsCell,
  HttpsCell,
  MODE_OPTIONS,
  Mode,
  NOTIFY_STATES,
  PROVIDER_OPTIONS,
  PROXY_ADDR,
  Status,
  diagnosticsContextKey,
  errorText,
  getStatus,
  labelOf,
  runDiagnostics,
  setEnabled,
  setMode,
  setProvider,
  statusLabel,
} from "./api";

const toast = (body: string) => toaster.toast({ title: "DNS Unblock", body });

// The QAM remounts plugin content when a dropdown menu closes, so state that
// must survive a selection lives outside the component.
const sticky: Record<string, unknown> = {};
function useSticky<T>(key: string, initial: T): [T, (value: T) => void] {
  const [value, setValue] = useState<T>(key in sticky ? (sticky[key] as T) : initial);
  const set = (next: T) => {
    sticky[key] = next;
    setValue(next);
  };
  return [value, set];
}

// Short labels so the QAM table stays readable in a narrow sidebar.
const DNS_STYLE: Record<string, [string, string]> = {
  resolved: ["OK", "#59bf40"],
  ok: ["OK", "#59bf40"],
  possible_dns_blocking: ["Block", "#ff6b6b"],
  blocked: ["Block", "#ff6b6b"],
  lookup_failed: ["Fail", "#e6a23c"],
  unknown: ["-", "inherit"],
};

const HTTPS_STYLE: Record<string, [string, string]> = {
  reachable: ["OK", "#59bf40"],
  http_error: ["HTTP", "#e6a23c"],
  connection_failed: ["Fail", "#ff6b6b"],
  unknown: ["-", "inherit"],
};

// store.steampowered.com -> store, steamcommunity.com -> community
const shortDomain = (domain: string) => domain.split(".")[0].replace(/^steam/, "");

const CELL: React.CSSProperties = { padding: "2px 4px", textAlign: "left" };
const DIVIDER = "1px solid rgba(255, 255, 255, 0.1)";

function DiagnosticsTable({ rows }: { rows: Diagnostics["rows"] }) {
  const dnsCell = (v: DnsCell) => {
    const [text, color] = DNS_STYLE[v.verdict] ?? DNS_STYLE.unknown;
    return <td style={{ ...CELL, color, fontWeight: 600 }} title={v.detail}>{text}</td>;
  };
  const httpsCell = (v: HttpsCell) => {
    const [text, color] = HTTPS_STYLE[v.verdict] ?? HTTPS_STYLE.unknown;
    return <td style={{ ...CELL, color, fontWeight: 600 }} title={v.detail}>{text}</td>;
  };
  return (
    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "12px" }}>
      <thead>
        <tr style={{ opacity: 0.6 }}>
          {["Domain", "Net", "Prov", "Deck", "HTTPS"].map((h) => (
            <th key={h} style={{ ...CELL, fontWeight: 400 }}>{h}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.domain} style={{ borderTop: DIVIDER }}>
            <td style={CELL}>{shortDomain(row.domain)}</td>
            {dnsCell(row.network)}
            {dnsCell(row.provider)}
            {dnsCell(row.system)}
            {httpsCell(row.https)}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

const dnsName = (server: string) => (server === PROXY_ADDR ? "dnsproxy (DoH)" : server);

function StatusTable({ status }: { status: Status }) {
  const rows: [string, string][] = [
    ["Wi-Fi", status.device ? `${status.device} · ${status.connectivity}` : "-"],
    ["DNS", status.link_dns.map(dnsName).join(", ") || "-"],
    ["In use", status.current_dns ? dnsName(status.current_dns) : "-"],
  ];
  if (status.message) rows.push(["Note", status.message]);
  return (
    <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", columnGap: "10px", rowGap: "2px" }}>
      {rows.map(([label, value]) => (
        <Fragment key={label}>
          <span style={{ opacity: 0.6 }}>{label}</span>
          <span style={{ overflowWrap: "anywhere" }}>{value}</span>
        </Fragment>
      ))}
    </div>
  );
}

function StatusRow({ status }: { status?: Status }) {
  if (!status) return <Field label="Status">Loading...</Field>;
  return (
    <Field
      label="Status"
      description={<StatusTable status={status} />}
      childrenLayout="inline"
      focusable
      highlightOnFocus
    >
      {statusLabel(status)}
    </Field>
  );
}

function DiagnosticsSection({ status }: { status?: Status }) {
  const [result, setResult] = useSticky<Diagnostics | undefined>("diagnostics", undefined);
  const [running, setRunning] = useState(false);

  // Invalidate sticky results when mode / provider / device context changes.
  useEffect(() => {
    if (!status || !result?.context) return;
    const live = diagnosticsContextKey({
      mode: status.mode,
      provider: status.provider,
      active_provider: status.active_provider,
      device: status.device,
    });
    const stored = diagnosticsContextKey(result.context);
    if (live !== stored) setResult(undefined);
  }, [status?.mode, status?.provider, status?.active_provider, status?.device, result, setResult]);

  const run = async () => {
    setRunning(true);
    try {
      setResult(await runDiagnostics());
    } catch (e) {
      toast(`Diagnostics failed: ${errorText(e)}`);
    } finally {
      setRunning(false);
    }
  };

  const meta = result
    ? [
        result.network_dns.join(", ") || "no DHCP DNS",
        result.resolver,
      ].join(" · ")
    : "";

  return (
    <PanelSection title="Diagnostics">
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={run} disabled={running}>
          {running ? "Checking..." : "Run diagnostics"}
        </ButtonItem>
      </PanelSectionRow>
      {result && (
        <>
          <PanelSectionRow>
            <Field label="Result" description={result.summary} focusable highlightOnFocus />
          </PanelSectionRow>
          <PanelSectionRow>
            <Field
              label="Steam lookups"
              description={meta}
              childrenLayout="below"
              childrenContainerWidth="max"
              focusable
              highlightOnFocus
            >
              <DiagnosticsTable rows={result.rows} />
            </Field>
          </PanelSectionRow>
        </>
      )}
    </PanelSection>
  );
}

function Content() {
  const [status, setStatus] = useState<Status | undefined>();
  const [busy, setBusy] = useState(false);
  const [editingCustom, setEditingCustom] = useSticky("editingCustom", false);
  const [customText, setCustomText] = useSticky<string | undefined>("customText", undefined);

  useEffect(() => {
    getStatus().then((s) => {
      setStatus(s);
      if (customText === undefined) setCustomText(s.custom_servers.join(", "));
    }).catch((e) => toast(`Backend not responding: ${errorText(e)}`));
    const listener = addEventListener<[Status]>("status", setStatus);
    return () => { removeEventListener("status", listener); };
  }, []);

  // Runs a backend change, keeps the panel in sync and reports failures.
  const update = async (action: () => Promise<Status>, success?: (s: Status) => string) => {
    setBusy(true);
    try {
      const s = await action();
      setStatus(s);
      if (success) toast(success(s));
      return true;
    } catch (e) {
      toast(errorText(e));
      return false;
    } finally {
      setBusy(false);
    }
  };

  const onProvider = (provider: string) => {
    if (provider !== "custom") {
      setEditingCustom(false);
      update(() => setProvider(provider), () => `Provider: ${labelOf(PROVIDER_OPTIONS, provider)}`);
    } else if (status?.custom_servers.length) {
      update(() => setProvider("custom", status.custom_servers), () => "Provider: Custom");
    } else {
      setEditingCustom(true);
    }
  };

  const saveCustom = async () => {
    const servers = (customText ?? "").split(/[\s,]+/).filter(Boolean);
    if (await update(() => setProvider("custom", servers), () => "Custom DNS servers saved")) {
      setEditingCustom(false);
    }
  };

  const showCustom = editingCustom || status?.provider === "custom";
  const disabled = !status || busy;

  return (
    <>
      <PanelSection>
        <PanelSectionRow>
          <ToggleField
            label="Bypass Steam block"
            description="Encrypted DNS on any Wi-Fi"
            checked={status?.enabled ?? false}
            disabled={disabled}
            onChange={(enabled) => update(() => setEnabled(enabled))}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <StatusRow status={status} />
        </PanelSectionRow>
      </PanelSection>
      <PanelSection title="Settings">
        <PanelSectionRow>
          <DropdownItem
            label="Mode"
            rgOptions={MODE_OPTIONS}
            selectedOption={status?.mode}
            disabled={disabled}
            onChange={(o) => update(() => setMode(o.data as Mode), () => `Mode: ${labelOf(MODE_OPTIONS, o.data)}`)}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <DropdownItem
            label="Provider"
            rgOptions={PROVIDER_OPTIONS}
            selectedOption={editingCustom ? "custom" : status?.provider}
            disabled={disabled}
            onChange={(o) => onProvider(o.data)}
          />
        </PanelSectionRow>
        {showCustom && (
          <>
            <PanelSectionRow>
              <TextField
                label="Custom DNS servers"
                description="IPv4/IPv6, comma-separated"
                value={customText ?? ""}
                disabled={disabled}
                onChange={(e) => setCustomText(e.target.value)}
              />
            </PanelSectionRow>
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={saveCustom} disabled={disabled}>
                Save custom servers
              </ButtonItem>
            </PanelSectionRow>
          </>
        )}
      </PanelSection>
      <DiagnosticsSection status={status} />
    </>
  );
};

export default definePlugin(() => {
  let lastState: string | undefined;
  const listener = addEventListener<[Status]>("status", (s) => {
    if (lastState !== undefined && s.state !== lastState && NOTIFY_STATES.includes(s.state)) {
      toast(`${statusLabel(s)}${s.message ? `: ${s.message}` : ""}`);
    }
    lastState = s.state;
  });

  return {
    // The name shown in various decky menus
    name: "DNS Unblock",
    // The element displayed at the top of your plugin's menu
    titleView: <div className={staticClasses.Title}>DNS Unblock</div>,
    // The content of your plugin's menu
    content: <Content />,
    // The icon displayed in the plugin list
    icon: <FaShieldAlt />,
    onDismount() {
      removeEventListener("status", listener);
    },
  };
});
