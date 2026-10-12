import {
  ButtonItem,
  Field,
  PanelSection,
  PanelSectionRow,
  ToggleField,
  staticClasses
} from "@decky/ui";
import {
  addEventListener,
  callable,
  definePlugin,
  removeEventListener,
  toaster,
} from "@decky/api"
import { useEffect, useState } from "react";
import { FaShieldAlt } from "react-icons/fa";

type Status = {
  enabled: boolean;
  mode: string;
  provider: string;
  custom_servers: string[];
  state: string;
  message: string;
  device: string | null;
  link_dns: string[];
  current_dns: string | null;
  connectivity: string;
};

const getStatus = callable<[], Status>("get_status");
const setEnabled = callable<[enabled: boolean], Status>("set_enabled");

function Content() {
  const [status, setStatus] = useState<Status | undefined>();
  const [busy, setBusy] = useState(false);

  const refresh = async () => setStatus(await getStatus());

  useEffect(() => {
    refresh();
    const listener = addEventListener<[Status]>("status", setStatus);
    return () => { removeEventListener("status", listener); };
  }, []);

  const onToggle = async (enabled: boolean) => {
    setBusy(true);
    try {
      setStatus(await setEnabled(enabled));
    } catch (e) {
      toaster.toast({ title: "DNS Unblock", body: `${e}` });
    } finally {
      setBusy(false);
    }
  };

  return (
    <PanelSection title="DNS Unblock">
      <PanelSectionRow>
        <ToggleField
          label="Bypass DNS block"
          checked={status?.enabled ?? false}
          disabled={!status || busy}
          onChange={onToggle}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <Field label="State" description={status?.message || undefined}>{status?.state ?? "..."}</Field>
      </PanelSectionRow>
      <PanelSectionRow>
        <Field label="Link DNS" description={status?.current_dns ? `in use: ${status.current_dns}` : undefined}>
          {status?.link_dns.join(", ") || "-"}
        </Field>
      </PanelSectionRow>
      <PanelSectionRow>
        <Field label="Network">{`${status?.device ?? "-"} (${status?.connectivity ?? "?"})`}</Field>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={refresh}>Refresh</ButtonItem>
      </PanelSectionRow>
    </PanelSection>
  );
};

export default definePlugin(() => {
  return {
    // The name shown in various decky menus
    name: "DNS Unblock",
    // The element displayed at the top of your plugin's menu
    titleView: <div className={staticClasses.Title}>DNS Unblock</div>,
    // The content of your plugin's menu
    content: <Content />,
    // The icon displayed in the plugin list
    icon: <FaShieldAlt />,
  };
});
