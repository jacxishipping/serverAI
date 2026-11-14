# Device heartbeat inventory

The shared Python agent sends a versioned inventory object on heartbeat:

```json
{
  "schema_version": 1,
  "runtime": {"python": "3.x", "machine": "...", "system": "...", "release": "..."},
  "capabilities": ["desktop.capture", "desktop.input", "inventory.installed_apps", "inventory.installed_tools", "task.polling", "telemetry.system_metrics"],
  "installed_tools": ["git", "python"],
  "installed_apps": [{"name": "Example", "source": "standard_application_directory"}]
}
```

The server also stores the capability list in its dedicated device field for
filtering. Inventory is limited to 32 KB server-side; the Python agent caps
application names at 100 entries and tool names at a fixed allowlist. It sends
names only, with no install paths or versions. Windows reads standard uninstall
registry entries; macOS and Linux inspect standard application directories.
Collection is best-effort and cached for the life of the agent process so
registry and filesystem enumeration does not run on every heartbeat. Changes
to installed software appear after agent restart.

This is not a complete software asset inventory: per-user custom install paths,
package-manager-only server software, hidden applications, and native Windows
agent telemetry are not guaranteed to appear. Capability names describe the
shared Python agent's supported surface, not a live probe of every permission,
device, or dependency on the host. Platform execution and parity still require
host validation.
