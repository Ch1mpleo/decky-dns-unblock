import {
  ButtonItem,
  PanelSection,
  PanelSectionRow,
  staticClasses
} from "@decky/ui";
import {
  callable,
  definePlugin,
} from "@decky/api"
import { useState } from "react";
import { FaShieldAlt } from "react-icons/fa";

type PingResult = { pong: boolean; uid: number; plugin_dir: string };

const ping = callable<[], PingResult>("ping");

function Content() {
  const [result, setResult] = useState<string | undefined>();

  const onClick = async () => {
    try {
      const r = await ping();
      setResult(`Backend OK (uid ${r.uid})`);
    } catch (e) {
      setResult(`Backend error: ${e}`);
    }
  };

  return (
    <PanelSection title="DNS Unblock">
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          onClick={onClick}
        >
          {result ?? "Ping backend"}
        </ButtonItem>
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
