# Booking MCP runbook

Owner: SoloAI operator and booking service owner.

| Symptom | Check and action | Recovery evidence |
|---|---|---|
| Local support snapshot shown | Confirm SOLOAI_MCP_CONFIG_FILE is exported in both processes and has an entry for the internal workspace ID | Booking integration says MCP booking |
| Configuration error / mcp_configuration_invalid | Validate JSON shape, file access, exact allowlist URL, HTTPS and credential length. Never print token values | Status shows configured; execute a synthetic lookup |
| mcp_unavailable_or_invalid | Generic safe failure can represent 401, 403, server outage, malformed output, oversized response or SDK failure. Check the booking service's redacted operational logs and credential mapping | Known booking returns validated fields |
| tool_timeout | Check server latency and network route. Keep the bounded timeout; do not blindly retry uncertain jobs | Lookup completes within four seconds |
| Booking missing for one tenant | Verify credential-to-tenant mapping and that tenant's data. Never substitute another tenant's token | Known record visible only to its owner |
| Manual draft does not use MCP | MCP is connected to queued email execution, not /api/try | New Gmail/event job records get_booking metadata |
| More tools are advertised remotely | Expected: SoloAI invokes only the fixed get_booking tool | No unapproved calls appear |

Containment: disable Email Support or use the stop control. Revoke a compromised credential at the booking service, replace it in the secret file and test with synthetic data. Keep remote credentials unique by tenant. Removing a tenant entry deliberately switches future jobs back to local snapshots, so do not use removal as an outage workaround without checking data freshness.

Record timestamps, safe error code, tool duration and execution state. Never attach bearer tokens, config files, callback URLs, customer messages or complete remote responses. Verify recovery with one permitted lookup and one other-tenant denial. Automatic retries are not implemented in the MCP adapter.
