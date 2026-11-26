"use strict";
/**
 * MAD SEAL — the verdict in the signing path.
 *
 * One call before any signature: is the counterparty live, is the
 * authorization sane, is the price the claimed price.
 *
 * Grade -> Cap -> Settle -> Witness. 0.01 USDC per seal on the public door.
 *
 * Node 18+, zero dependencies (global fetch). CommonJS.
 * ESM:  import pkg from "./mad-seal.js"; const { wrapSigner } = pkg;
 * CJS:  const { wrapSigner } = require("./mad-seal.js");
 *
 * API contract: POST /v1/seal/verdict — see README.md.
 * The settle pair: POST /v1/seal/open pins the expected terms of a
 * settlement in a witness-anchored receipt before it lands;
 * POST /v1/seal/close checks the tx that actually landed against
 * them and answers SEALED or DRIFT. GET /v1/seal/{seal_id} returns
 * the paired record.
 */

const crypto = require("crypto");

const DEFAULT_API = "https://api.madcheck.xyz";
// Local door: http://127.0.0.1:8402

class SealError extends Error {
  constructor(message) {
    super(message);
    this.name = "SealError";
  }
}

class SealRefused extends SealError {
  constructor(verdict, message) {
    const reasons = verdict && verdict.reasons ? verdict.reasons : "";
    super(message || `MAD SEAL: DONT_SIGN ${reasons}`.trim());
    this.name = "SealRefused";
    this.verdict = verdict;
  }
}

class SealCaution extends SealError {
  constructor(verdict, message) {
    const reasons = verdict && verdict.reasons ? verdict.reasons : "";
    super(message || `MAD SEAL: CAUTION ${reasons}`.trim());
    this.name = "SealCaution";
    this.verdict = verdict;
  }
}

function baseOf(apiUrl) {
  return (apiUrl || DEFAULT_API).replace(/\/+$/, "");
}

async function fetchWithTimeout(url, options, timeoutMs) {
  const ms = timeoutMs == null ? 10000 : timeoutMs;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), ms);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

/**
 * POST to {apiUrl}/v1/seal/verdict. Returns the full payload dict
 * (envelope keys service/version/ts ride along at top level).
 */
async function sealVerdict(request, opts = {}) {
  const apiUrl = opts.apiUrl || DEFAULT_API;
  const timeoutMs = opts.timeoutMs == null ? 10000 : opts.timeoutMs;
  let res;
  try {
    res = await fetchWithTimeout(
      `${baseOf(apiUrl)}/v1/seal/verdict`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(request),
      },
      timeoutMs
    );
  } catch (err) {
    throw new SealError(`seal verdict transport error: ${err.message}`);
  }
  const text = await res.text();
  if (!res.ok) {
    throw new SealError(`seal verdict HTTP ${res.status}: ${text.slice(0, 500)}`);
  }
  try {
    return JSON.parse(text);
  } catch {
    throw new SealError(`seal verdict returned non-JSON: ${text.slice(0, 500)}`);
  }
}

async function postJson(path, payload, opts, label) {
  const apiUrl = opts.apiUrl || DEFAULT_API;
  const timeoutMs = opts.timeoutMs == null ? 10000 : opts.timeoutMs;
  let res;
  try {
    res = await fetchWithTimeout(
      `${baseOf(apiUrl)}${path}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(payload),
      },
      timeoutMs
    );
  } catch (err) {
    throw new SealError(`${label} transport error: ${err.message}`);
  }
  const text = await res.text();
  if (!res.ok) {
    throw new SealError(`${label} HTTP ${res.status}: ${text.slice(0, 500)}`);
  }
  try {
    return JSON.parse(text);
  } catch {
    throw new SealError(`${label} returned non-JSON: ${text.slice(0, 500)}`);
  }
}

/**
 * POST to {apiUrl}/v1/seal/open. Returns the full payload dict.
 * On success: opened=true, seal_id, verdict (SIGN or CAUTION),
 * expected, seal. On DONT_SIGN: opened=false plus the verdict
 * receipt — nothing opens, and this does not throw for it.
 * Re-opening the same authorization (same nonce) returns the
 * existing seal with already_open=true.
 */
async function openSeal(request, opts = {}) {
  return postJson("/v1/seal/open", request, opts, "seal open");
}

/**
 * POST to {apiUrl}/v1/seal/close. Returns the full payload dict:
 * outcome "SEALED" (the chain matches the opened terms) or "DRIFT"
 * (see reasons and deltas), expected vs actual, open_seq /
 * close_seq, already_closed, seal. opts may carry chainId (plus
 * apiUrl / timeoutMs). Re-closing the same seal + tx returns the
 * stored outcome with already_closed=true. Default timeout is
 * 30s: close reads the settlement back from chain.
 */
async function closeSeal(sealId, txHash, opts = {}) {
  if (!sealId || !txHash) throw new SealError("sealId and txHash are required");
  const body = { seal_id: sealId, txHash };
  if (opts.chainId != null) body.chainId = opts.chainId;
  const closeOpts = { timeoutMs: 30000, ...opts };
  return postJson("/v1/seal/close", body, closeOpts, "seal close");
}

/**
 * Canonical JSON matching Python's json.dumps(sort_keys=True,
 * separators=(",",":")) for the receipt payload shapes the witness
 * ledger stores (plain JSON values). Keys are sorted recursively.
 */
function canonicalJson(value) {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return "[" + value.map(canonicalJson).join(",") + "]";
  const keys = Object.keys(value).sort();
  return "{" + keys.map((k) => JSON.stringify(k) + ":" + canonicalJson(value[k])).join(",") + "}";
}

function sha256Hex(input) {
  return crypto.createHash("sha256").update(input, "utf8").digest("hex");
}

/**
 * Verify a seal receipt against the witness ledger.
 * GET {apiUrl}/v1/witness/{seq}; recompute both hashes.
 * Returns true only if every check passes.
 */
async function verifySeal(seal, opts = {}) {
  const apiUrl = opts.apiUrl || DEFAULT_API;
  const timeoutMs = opts.timeoutMs == null ? 10000 : opts.timeoutMs;
  if (!seal || seal.witness_seq == null) return false;
  let entry;
  try {
    const res = await fetchWithTimeout(
      `${baseOf(apiUrl)}/v1/witness/${seal.witness_seq}`,
      { headers: { Accept: "application/json" } },
      timeoutMs
    );
    if (!res.ok) return false;
    entry = await res.json();
  } catch {
    return false;
  }
  const { receipt_payload, receipt_sha256, prev_hash, entry_hash, ts } = entry;
  if (receipt_payload == null || !receipt_sha256 || prev_hash == null || !entry_hash || ts == null) {
    return false;
  }
  if (sha256Hex(canonicalJson(receipt_payload)) !== receipt_sha256) return false;
  if (sha256Hex(`${prev_hash}${receipt_sha256}${ts}`) !== entry_hash) return false;
  if (seal.receipt_sha256 && seal.receipt_sha256 !== receipt_sha256) return false;
  if (seal.entry_hash && seal.entry_hash !== entry_hash) return false;
  return true;
}

function gate(payload, allowCaution) {
  const verdict = payload && payload.verdict;
  if (verdict === "DONT_SIGN") throw new SealRefused(payload);
  if (verdict === "CAUTION" && !allowCaution) throw new SealCaution(payload);
  if (verdict !== "SIGN" && verdict !== "CAUTION") {
    throw new SealError(`unexpected verdict: ${verdict}`);
  }
  return payload;
}

async function signerAddress(signer) {
  if (signer.address != null) return signer.address;
  if (typeof signer.getAddress === "function") return signer.getAddress();
  return undefined;
}

/**
 * Wrap an ethers-style signer. Returns an object with async
 * signTransaction(tx), sendTransaction(tx), signAuthorization(auth, counterparty).
 * Each returns [result, seal]. DONT_SIGN -> SealRefused; CAUTION without
 * opts.allowCaution -> SealCaution; the wrapped signer is never called
 * on a gated verdict.
 *
 * opts: { apiUrl, counterparty, caps, allowCaution, agentId, timeoutMs, client }
 */
function wrapSigner(signer, opts = {}) {
  const apiUrl = opts.apiUrl || DEFAULT_API;
  const timeoutMs = opts.timeoutMs == null ? 10000 : opts.timeoutMs;
  const allowCaution = !!opts.allowCaution;

  async function verdictForTx(tx) {
    const request = {
      chainId: tx.chainId != null ? tx.chainId : 8453,
      from: tx.from || (await signerAddress(signer)),
      to: tx.to,
      value: tx.value != null ? String(tx.value) : undefined,
      data: tx.data,
    };
    if (tx.submitter) request.submitter = tx.submitter;
    if (opts.counterparty != null) request.counterparty = opts.counterparty;
    if (opts.caps != null) request.caps = opts.caps;
    if (opts.agentId != null) request.agentId = opts.agentId;
    if (opts.client != null) request.client = opts.client;
    for (const k of Object.keys(request)) if (request[k] === undefined) delete request[k];
    return sealVerdict(request, { apiUrl, timeoutMs });
  }

  async function verdictForAuthorization(auth, counterparty) {
    const request = {
      chainId: auth.chainId != null ? auth.chainId : 8453,
      from: auth.from || (await signerAddress(signer)),
      to: auth.to,
      authorization: auth,
      counterparty: counterparty != null ? counterparty : opts.counterparty,
    };
    if (opts.caps != null) request.caps = opts.caps;
    if (opts.agentId != null) request.agentId = opts.agentId;
    if (opts.client != null) request.client = opts.client;
    for (const k of Object.keys(request)) if (request[k] === undefined) delete request[k];
    return sealVerdict(request, { apiUrl, timeoutMs });
  }

  return {
    signer,
    verdictForTx,

    async signTransaction(tx) {
      const payload = gate(await verdictForTx(tx), allowCaution);
      if (typeof signer.signTransaction !== "function") {
        throw new SealError("signer has no signTransaction");
      }
      const sig = await signer.signTransaction(tx);
      return [sig, payload.seal];
    },

    async sendTransaction(tx) {
      const payload = gate(await verdictForTx(tx), allowCaution);
      if (typeof signer.sendTransaction !== "function") {
        throw new SealError("signer has no sendTransaction");
      }
      const result = await signer.sendTransaction(tx);
      return [result, payload.seal];
    },

    async signAuthorization(auth, counterparty) {
      const payload = gate(await verdictForAuthorization(auth, counterparty), allowCaution);
      const seal = payload.seal;
      if (typeof signer.signAuthorization === "function") {
        return [await signer.signAuthorization(auth), seal];
      }
      // ethers signers sign typed data / messages; prefer signMessage.
      if (typeof signer.signMessage === "function") {
        return [await signer.signMessage(auth), seal];
      }
      if (typeof signer.signTypedData === "function") {
        return [await signer.signTypedData(auth), seal];
      }
      throw new SealError("signer cannot sign authorizations");
    },

    /**
     * Open a seal over an intended settlement. Returns the payload.
     * The wrapper's counterparty / caps / agentId / client fill in
     * any the intent leaves out. Throws SealRefused when the verdict
     * is DONT_SIGN (opened === false). CAUTION opens.
     */
    async openSeal(intent) {
      const request = { ...intent };
      if (request.counterparty == null && opts.counterparty != null) request.counterparty = opts.counterparty;
      if (request.caps == null && opts.caps != null) request.caps = opts.caps;
      if (request.agentId == null && opts.agentId != null) request.agentId = opts.agentId;
      if (request.client == null && opts.client != null) request.client = opts.client;
      for (const k of Object.keys(request)) if (request[k] === undefined) delete request[k];
      const payload = await openSeal(request, { apiUrl, timeoutMs });
      if (!payload.opened || payload.verdict === "DONT_SIGN") {
        throw new SealRefused(payload);
      }
      return payload;
    },

    /**
     * Close an opened seal against the settlement tx that landed.
     * Returns the close payload (outcome SEALED or DRIFT, reasons,
     * deltas, expected vs actual, open_seq / close_seq, seal).
     * DRIFT is a result, not a throw — read the payload.
     */
    async closeSeal(sealId, txHash, chainId) {
      return closeSeal(sealId, txHash, {
        apiUrl,
        timeoutMs: Math.max(timeoutMs, 30000),
        chainId,
      });
    },

    /**
     * The full pair around a caller-supplied settlement: open a
     * seal over intent, call settleFn(intent) -> txHash (the
     * caller's own code performs and broadcasts the settlement;
     * MAD never signs or sends), then close the seal against that
     * tx hash and return the close payload. On DONT_SIGN,
     * SealRefused throws before settleFn is ever called.
     */
    async settle(intent, settleFn) {
      const opened = await this.openSeal(intent);
      const txHash = await settleFn(intent);
      if (!txHash) throw new SealError("settleFn returned no tx hash");
      return this.closeSeal(opened.seal_id, txHash, intent.chainId);
    },
  };
}

module.exports = {
  DEFAULT_API,
  SealError,
  SealRefused,
  SealCaution,
  sealVerdict,
  verifySeal,
  openSeal,
  closeSeal,
  wrapSigner,
  // snake_case aliases matching the spec's function names
  seal_verdict: sealVerdict,
  verify_seal: verifySeal,
  open_seal: openSeal,
  close_seal: closeSeal,
};
