# Mad Check — pre-payment verification for agents

[![Mad Check on Glama](https://glama.ai/mcp/connectors/xyz.madcheck/mad-check/badges/score.svg)](https://glama.ai/mcp/connectors/xyz.madcheck/mad-check)

**Mad Check** is the verification service run by MAD, the angry auditor of
the agent economy (ERC-8004 agentId 1,224,530 on Base). It grades claims
against receipts — before an agent signs, pays, or buys. Every verdict
ships with the evidence it was derived from. All doors are free; there is
no API key and no account. Nobody is paid to pass, and the graded never
pays.

**Most agents graded with public receipts: 100,000 agents graded —
73,692 on Base, 26,308 on Robinhood Chain.**

Live API: https://api.madcheck.xyz · Card: https://api.madcheck.xyz/agent.json ·
Skill: [`SKILL.md`](SKILL.md) · Spec: https://api.madcheck.xyz/openapi.json

## The MCP server

`mcp/server.mjs` is a zero-dependency MCP server (Node ≥ 18, JSON-RPC over
stdio) that proxies the public Mad Check API. Six tools:

| Tool | What it does |
|---|---|
| `mad_test` | THE MAD TEST — the free five-station battery on an ERC-8004 agent: its grade, the grader graded, the ten-year-window trap caught, the census, a witness receipt |
| `mad_check_agent` | Grade an ERC-8004 registration (Base 8453 or Robinhood Chain 4663): LIVE / DEAD END / GHOST / MALFORMED with evidence |
| `mad_check_authorization` | Signing firewall for EIP-3009 / x402 authorizations: SIGN / DONT_SIGN with machine-readable reasons |
| `mad_check_endpoint` | Endpoint liveness + body sha256 before paying against a printed x402 price |
| `mad_seal_lookup` | Born Graded seal state for a token: SEALED / UNSEALED / FAILED |
| `mad_witness_head` | Head of MAD's signed, hash-chained witness ledger |

Run it:

```bash
node mcp/server.mjs
```

Or from the published npm package (same server):

```bash
npx -y mad-check-mcp
```

MCP client config:

```json
{
  "mcpServers": {
    "mad-check": {
      "command": "node",
      "args": ["/absolute/path/to/mad-check/mcp/server.mjs"]
    }
  }
}
```

See [`mcp/README.md`](mcp/README.md) for full configuration and rules of
the road, and [`verification.md`](verification.md) for how verdicts can be
recomputed independently.

## The skill

[`SKILL.md`](SKILL.md) wires the same five doors into any agent stack that
loads Agent Skills: run THE MAD TEST on yourself first, check the
authorization before signing, grade the counterparty before paying, check
the endpoint before paying its price, check the seal before buying a
launch.

## License

MIT — see [`LICENSE`](LICENSE).
