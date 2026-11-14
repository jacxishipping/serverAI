# Browser session security

Playwright sessions are isolated by MCP principal. Over Streamable HTTP, the
principal is the SHA-256 digest of the bearer token; the token itself is never
used as a browser session identifier or stored by the browser manager. Anonymous
HTTP calls cannot use browser tools. A stdio server uses one process-local
profile, which matches the single-client stdio process model.

Each principal gets a distinct Chromium browser and context, hosted on one owner
thread so synchronous Playwright state is not shared across principals or used
from arbitrary worker threads. `browser_close` closes only the caller's
context. Idle browser workers stop after 15 minutes. A shared bearer token
intentionally represents one principal; deploy distinct user tokens when
callers need separate browser profiles.

Profiles are in-memory by default. Set
`AI_BRIDGE_BROWSER_PERSIST_PROFILES=1` to persist each isolated profile under
`<AI_BRIDGE_DATA_DIR>/browser-profiles/<principal-digest>`. The directory is
restricted to the service account on POSIX systems. Persistent profiles can
contain authenticated cookies and local storage; include them in the same
secret-handling, backup, retention, and host-permission controls as credentials.
`browser_close` keeps the profile on disk in this mode.

## Destination policy

By default, browser navigation and downloads allow HTTPS destinations whose DNS
answers are all public IP addresses. The context checks each HTTP request,
including redirects and subresources, and blocks private, loopback, link-local,
reserved, and non-global destinations. Embedded URL credentials and
nonstandard ports are rejected.

For a trusted internal website or local development endpoint, set
`AI_BRIDGE_BROWSER_ALLOWED_HOSTS` to a comma-separated list of exact hostnames
(no wildcards), for example:

```text
AI_BRIDGE_BROWSER_ALLOWED_HOSTS=localhost,staging.example.internal
```

An exact allowlisted host may use HTTP, a nonstandard port, or a private IP.
Protect this environment setting as an administrator-controlled network access
policy. Do not add broad parent domains or hosts that resolve to untrusted
addresses. Download names are reduced to a plain basename and downloads over
100 MiB are rejected.

This browser-level policy is defense in depth. Production deployments handling
untrusted pages should also enforce outbound network restrictions at the
container/host boundary to protect against DNS rebinding and browser/network
stack behavior outside Playwright routing.
