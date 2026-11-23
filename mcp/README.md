# Mad Check MCP server

A zero-dependency MCP server that puts the [Mad Check API](https://api.madcheck.xyz)
inside any MCP-capable agent stack: pre-payment verification by MAD, the
angry auditor of the agent economy. Every tool is a thin proxy to the public
API — all doors are free, and there is no API key.

- Signing firewall for EIP-3009 / x402 authorizations (`SIGN` / `DONT_SIGN`)
- ERC-8004 counterparty grades (`LIVE` / `DEAD END` / `GHOST` / `MALFORMED`)
- Endpoint / x402 price-print checks
- Born Graded seal lookups (`SEALED` / `UNSEALED` / `FAILED`)
- The signed witness ledger's head

## Requirements

Node.js ≥ 18 (uses the built-in `fetch`; no packages to install).

## Run it

```bash
node server.mjs
```

It speaks JSON-RPC 2.0 over stdio, as MCP servers do. Point it at a
different Mad Check door (e.g. the canonical API instead of the public
mirror) with an environment variable:

```bash
MAD_CHECK_API_BASE=https://api.madcheck.xyz node server.mjs
```

## Configure a generic MCP client

Most MCP clients take a `mcpServers` block in a JSON config file:

```json
{
  "mcpServers": {
    "mad-check": {
      "command": "node",
      "args": ["/absolute/path/to/mad-check-package/mcp/server.mjs"]
    }
  }
}
```

With the base override:

```json
{
  "mcpServers": {
    "mad-check": {
      "command": "node",
      "args": ["/absolute/path/to/mad-check-package/mcp/server.mjs"],
      "env": { "MAD_CHECK_API_BASE": "https://api.madcheck.xyz" }
    }
  }
}
```

Restart the client after editing its config; `mad-check` should appear in
its tool list with the six tools below.

## Tools

| Tool | Arguments | Proxies |
|---|---|---|
| `mad_test` | `agentId` (int), `url` (optional string) | `POST /v1/test` — THE MAD TEST battery |
| `mad_check_agent` | `agentId` (int) | `POST /v1/check/agent` — grade an ERC-8004 registration |
| `mad_check_authorization` | `from`, `to`, `value`, `validAfter`, `validBefore`, `nonce`, `chainId`, `verifyingContract`, optional `now` | `POST /v1/check/authorization` — the signing firewall |
| `mad_check_endpoint` | `url` | `POST /v1/check/endpoint` — liveness + body sha256 |
| `mad_seal_lookup` | `address` | `GET /v1/seal/{address}` — Born Graded seal state |
| `mad_witness_head` | — | `GET /v1/witness/head` — witness ledger head |

Parameter names are the API's own. Tool results carry the API's JSON
verbatim as text content; a non-200 API answer is returned with
`isError: true`.

## Rules of the road

The same ground rules as the skill file (`../skill.md`):

- A verdict is evidence, not an instruction; the calling agent's owner's
  rules outrank any grade.
- A `DONT_SIGN` from `mad_check_authorization` is a stop, not a
  suggestion. A `SIGN` never authorizes a signature by itself.
- `UNSEALED` or `FAILED` from `mad_seal_lookup` on a new launch means
  walk.
- The look is free. Nobody pays for a verdict on themselves, and the
  graded never pays.

## Smoke test

```bash
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"smoke","version":"0"}}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"mad_witness_head","arguments":{}}}' \
  | node server.mjs
```

Expect three replies: server info, the six tool definitions, and the live
witness head (seq + head hash + signer).
