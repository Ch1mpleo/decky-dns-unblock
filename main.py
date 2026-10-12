import os

# The decky plugin module is located at decky-loader/plugin
# For easy intellisense checkout the decky-loader code repo
# and add the `decky-loader/plugin/imports` path to `python.analysis.extraPaths` in `.vscode/settings.json`
import decky


class Plugin:
    # Milestone 0 smoke test: proves the frontend can reach the backend and that it runs as root.
    async def ping(self) -> dict:
        return {"pong": True, "uid": os.getuid(), "plugin_dir": decky.DECKY_PLUGIN_DIR}

    async def _main(self):
        decky.logger.info("DNS Unblock loaded")

    async def _unload(self):
        decky.logger.info("DNS Unblock unloading")

    async def _uninstall(self):
        decky.logger.info("DNS Unblock uninstalled")
