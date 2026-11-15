# Device heartbeat inventory

The shared Python agent sends a versioned inventory object on heartbeat:

```json
{
  "schema_version": 1,
  "runtime": {"python": "3.x", "machine": "...", "system": "...", "release": "..."},
  "capabilities": ["desktop.capture", "desktop.input", "inventory.installed_apps", "inventory.installed_tools", "task.polling", "telemetry.system_metrics"],
  "installed_tools": ["git", "python"],
  "installed_apps": [{"name": "Example", "source": "standard_application_directory"}],
  "process_count": 142,
  "processes": [{"name": "python.exe", "memory_mb": 120.5}],
  "connection_health": {"control_plane": "connected", "last_heartbeat_at": 1794700000.0}
}
```

The server also stores the capability list in its dedicated device field for
filtering. Inventory is limited to 32 KB server-side; the Python agent caps
application names at 100 entries and tool names at a fixed allowlist. It sends
process names and approximate resident memory for at most 50 processes, without
command lines, paths or usernames. That snapshot refreshes at most once every
30 seconds. Application names are sent without install paths or versions. Windows reads standard uninstall
registry entries; macOS and Linux inspect standard application directories.
Collection is best-effort and cached for the life of the agent process so
registry and filesystem enumeration does not run on every heartbeat. Changes
to installed software appear after agent restart.

This is not a complete software asset inventory: per-user custom install paths,
package-manager-only server software, hidden applications, and native Windows
agent telemetry are not guaranteed to appear. Capability names describe the
shared Python agent's supported surface, not a live probe of every permission,
device, or dependency on the host. Platform execution and parity still require
host validation. The control plane stamps the time it receives the heartbeat;
it does not claim end-to-end connectivity beyond that successful request.
