#!/usr/bin/env node
// Mad Check MCP server — thin proxy to the public Mad Check API.
// Zero dependencies: JSON-RPC 2.0 over stdio, Node >= 18 (global fetch).
// Tools proxy https://api.madcheck.xyz (override with MAD_CHECK_API_BASE).
// All doors are free; no API key exists or is needed.

import { createInterface } from "node:readline";

const BASE = (process.env.MAD_CHECK_API_BASE || "https://api.madcheck.xyz").replace(/\/$/, "");
const PROTOCOL_VERSION = "2024-11-05";
const SERVER_INFO = { name: "mad-check", version: "1.0.0" };

const TOOLS = [
  {
    name: "mad_test",
    description:
      "THE MAD TEST: run the free five-station battery on an ERC-8004 agent (Base): its grade with evidence, the grader graded by the same machine, the F-01 ten-year-window trap caught by the signing firewall, the registry census, and a witness receipt hash. Run it on yourself first.",
    inputSchema: {
      type: "object",
      properties: {
        agentId: { type: "integer", description: "Base ERC-8004 agentId to test" },
        url: { type: "string", description: "Optional: one of the agent's endpoints to add as a sixth station" },
      },
      required: ["agentId"],
    },
    route: { method: "POST", path: "/v1/test" },
  },
  {
    name: "mad_check_agent",
    description:
      "Grade an ERC-8004 registration on Base before paying its owner: LIVE / DEAD END / GHOST / MALFORMED with evidence (owner, card, services, endpoint probes). ERROR means the check itself could not complete — it is not a grade.",
    inputSchema: {
      type: "object",
      properties: { agentId: { type: "integer", description: "Base ERC-8004 agentId" } },
      required: ["agentId"],
    },
    route: { method: "POST", path: "/v1/check/agent" },
  },
  {
    name: "mad_check_authorization",
    description:
      "Signing firewall for EIP-3009 / x402 authorizations. Call BEFORE signing, every time. Returns SIGN or DONT_SIGN with machine-readable reasons. A DONT_SIGN is a stop, not a suggestion; a SIGN is evidence, not an instruction — the caller's own policy still decides.",
    inputSchema: {
      type: "object",
      properties: {
        from: { type: "string" },
        to: { type: "string" },
        value: { type: "string", description: "Amount in the token's smallest unit, as a string" },
        validAfter: { type: "integer", description: "Unix seconds" },
        validBefore: { type: "integer", description: "Unix seconds" },
        nonce: { type: "string", description: "bytes32 hex nonce" },
        chainId: { type: "integer" },
        verifyingContract: { type: "string", description: "Token contract (e.g. USDC on Base)" },
        now: { type: "integer", description: "Optional: pin evaluation time, unix seconds" },
      },
      required: ["from", "to", "value", "validAfter", "validBefore", "nonce", "chainId", "verifyingContract"],
    },
    route: { method: "POST", path: "/v1/check/authorization" },
  },
  {
    name: "mad_check_endpoint",
    description:
      "Check an endpoint before paying against its printed x402 price: HTTP status, latency, sha256 of the body served, and whether it is alive at all. A dead door's price print is a price for nothing.",
    inputSchema: {
      type: "object",
      properties: { url: { type: "string" } },
      required: ["url"],
    },
    route: { method: "POST", path: "/v1/check/endpoint" },
  },
  {
    name: "mad_seal_lookup",
    description:
      "Born Graded seal lookup: before buying a newly launched token, get its seal state — SEALED (claim sheet filed, anchored, graded against the contracts), UNSEALED (no graded sheet backs it), or FAILED (graded and contradicted). UNSEALED or FAILED on a new launch means walk.",
    inputSchema: {
      type: "object",
      properties: { address: { type: "string", description: "Token contract address (exact address, never a ticker)" } },
      required: ["address"],
    },
    route: { method: "GET", path: "/v1/seal/{address}", pathParam: "address" },
  },
  {
    name: "mad_witness_head",
    description:
      "Read the head of MAD's signed, hash-chained witness ledger (latest seq + head hash + signer). Entries are readable individually at GET /v1/witness/{seq} on the API.",
    inputSchema: { type: "object", properties: {} },
    route: { method: "GET", path: "/v1/witness/head" },
  },
];

async function callTool(tool, args) {
  let path = tool.route.path;
  const body = { ...(args || {}) };
  if (tool.route.pathParam) {
    const v = body[tool.route.pathParam];
    if (typeof v !== "string" || !v) throw new Error(`missing required argument: ${tool.route.pathParam}`);
    path = path.replace(`{${tool.route.pathParam}}`, encodeURIComponent(v));
    delete body[tool.route.pathParam];
  }
  const init = { method: tool.route.method, headers: { "Content-Type": "application/json" } };
  if (tool.route.method === "POST") init.body = JSON.stringify(body);
  const res = await fetch(BASE + path, init);
  const text = await res.text();
  let parsed;
  try { parsed = JSON.parse(text); } catch { parsed = text; }
  return { status: res.status, ok: res.ok, payload: parsed };
}

function send(obj) {
  process.stdout.write(JSON.stringify(obj) + "\n");
}
function reply(id, result) { send({ jsonrpc: "2.0", id, result }); }
function replyError(id, code, message) { send({ jsonrpc: "2.0", id, error: { code, message } }); }

async function handle(msg) {
  const { id, method, params } = msg;
  if (id === undefined || id === null) return; // notification: nothing to answer
  try {
    switch (method) {
      case "initialize":
        return reply(id, {
          protocolVersion: params?.protocolVersion || PROTOCOL_VERSION,
          capabilities: { tools: {} },
          serverInfo: SERVER_INFO,
        });
      case "ping":
        return reply(id, {});
      case "tools/list":
        return reply(id, {
          tools: TOOLS.map(({ name, description, inputSchema }) => ({ name, description, inputSchema })),
        });
      case "tools/call": {
        const tool = TOOLS.find((t) => t.name === params?.name);
        if (!tool) return replyError(id, -32602, `unknown tool: ${params?.name}`);
        try {
          const r = await callTool(tool, params.arguments || {});
          return reply(id, {
            content: [{ type: "text", text: JSON.stringify(r.payload, null, 2) }],
            isError: !r.ok,
            ...(r.ok ? {} : { _meta: { http_status: r.status } }),
          });
        } catch (e) {
          return reply(id, {
            content: [{ type: "text", text: `Mad Check API call failed: ${e.message}` }],
            isError: true,
          });
        }
      }
      default:
        return replyError(id, -32601, `method not found: ${method}`);
    }
  } catch (e) {
    return replyError(id, -32603, `internal error: ${e.message}`);
  }
}

const rl = createInterface({ input: process.stdin, crlfDelay: Infinity });
rl.on("line", (line) => {
  const s = line.trim();
  if (!s) return;
  let msg;
  try { msg = JSON.parse(s); } catch { return; }
  handle(msg);
});
