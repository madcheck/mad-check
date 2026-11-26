"""MAD SEAL — the verdict in the signing path.

One call before any signature: is the counterparty live, is the
authorization sane, is the price the claimed price.

Grade -> Cap -> Settle -> Witness. 0.01 USDC per seal on the public door.

Python, stdlib only (urllib). No third-party imports.

API contract: POST /v1/seal/verdict
  Request fields (all optional except as the server requires):
    chainId, from, to, value, data, submitter,
    authorization {spender, amount, windowSeconds, validAfter,
                   validBefore, verifyingContract, from},
    counterparty {agentId, address},
    caps {maxAmount, maxWindowSeconds},
    client, agentId
  Response: envelope {service, version, ts} + payload:
    verdict, reasons, evidence, caps, seal, price

API contract: the settle pair — POST /v1/seal/open + /v1/seal/close
  open:  body {chainId, payer, recipient, asset, amount,
         authorization {nonce, validAfter, validBefore, windowSeconds},
         counterparty, caps, client, agentId}
         -> {opened, seal_id, verdict, reasons, expected, seal}
         (verdict DONT_SIGN -> opened is False, no seal opens)
  close: body {seal_id, txHash, chainId}
         -> {seal_id, outcome: "SEALED"|"DRIFT", reasons, deltas,
             expected, actual, open_seq, close_seq, already_closed, seal}
  GET /v1/seal/{seal_id} returns the paired record.
"""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request

DEFAULT_API = "https://api.madcheck.xyz"
# Local door: http://127.0.0.1:8402


class SealError(Exception):
    """Base error for MAD SEAL failures (transport, protocol, signer)."""


class SealRefused(SealError):
    """DONT_SIGN verdict. Carries the full response payload in .verdict."""

    def __init__(self, verdict: dict, message: str | None = None):
        self.verdict = verdict
        reasons = verdict.get("reasons") if isinstance(verdict, dict) else None
        super().__init__(message or f"MAD SEAL: DONT_SIGN {reasons or ''}".strip())


class SealCaution(SealError):
    """CAUTION verdict raised when allow_caution is False.

    Carries the full response payload in .verdict.
    """

    def __init__(self, verdict: dict, message: str | None = None):
        self.verdict = verdict
        reasons = verdict.get("reasons") if isinstance(verdict, dict) else None
        super().__init__(message or f"MAD SEAL: CAUTION {reasons or ''}".strip())


def _post_json(url: str, payload: dict, timeout: float) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        raise SealError(f"seal verdict HTTP {exc.code}: {body[:500]}") from exc
    except urllib.error.URLError as exc:
        raise SealError(f"seal verdict transport error: {exc}") from exc
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise SealError(f"seal verdict returned non-JSON: {body[:500]}") from exc


def _get_json(url: str, timeout: float) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        raise SealError(f"witness fetch HTTP {exc.code}: {body[:500]}") from exc
    except urllib.error.URLError as exc:
        raise SealError(f"witness fetch transport error: {exc}") from exc
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise SealError(f"witness fetch returned non-JSON: {body[:500]}") from exc


def seal_verdict(request: dict, api_url: str = DEFAULT_API, timeout: float = 10) -> dict:
    """POST to {api_url}/v1/seal/verdict and return the payload dict.

    The envelope keys (service/version/ts) ride along; payload keys
    (verdict, reasons, evidence, caps, seal, price) are at top level.
    Nothing is unwrapped.
    """
    if not isinstance(request, dict):
        raise SealError("request must be a dict")
    base = (api_url or DEFAULT_API).rstrip("/")
    return _post_json(f"{base}/v1/seal/verdict", request, timeout)


def open_seal(request: dict, api_url: str = DEFAULT_API, timeout: float = 10) -> dict:
    """POST to {api_url}/v1/seal/open and return the payload dict.

    Opens a seal over an intended settlement: the verdict judges the
    authorization before it settles, and the expected terms (payer,
    recipient, asset, amount, nonce, window) are pinned in a
    witness-anchored receipt. On success the payload carries
    opened=True, seal_id, verdict (SIGN or CAUTION), expected and seal.
    On DONT_SIGN the payload carries opened=False and the verdict
    receipt — nothing opens, and this function does not raise for it;
    callers decide. Re-opening the same authorization (same nonce)
    returns the existing seal with already_open=True.
    """
    if not isinstance(request, dict):
        raise SealError("request must be a dict")
    base = (api_url or DEFAULT_API).rstrip("/")
    return _post_json(f"{base}/v1/seal/open", request, timeout)


def close_seal(
    seal_id: str,
    tx_hash: str,
    chain_id: int | None = None,
    api_url: str = DEFAULT_API,
    timeout: float = 30,
) -> dict:
    """POST to {api_url}/v1/seal/close and return the payload dict.

    Closes an opened seal against the settlement transaction that
    actually landed. The payload carries outcome "SEALED" (the chain
    matches the opened terms) or "DRIFT" (it does not — see reasons
    and deltas for the field-level differences), expected vs actual,
    open_seq / close_seq, and the close receipt in seal. Re-closing
    the same seal + tx returns the stored outcome with
    already_closed=True. The default timeout is longer than a
    verdict's: close reads the settlement back from chain.
    """
    if not seal_id or not tx_hash:
        raise SealError("seal_id and tx_hash are required")
    body: dict = {"seal_id": seal_id, "txHash": tx_hash}
    if chain_id is not None:
        body["chainId"] = chain_id
    base = (api_url or DEFAULT_API).rstrip("/")
    return _post_json(f"{base}/v1/seal/close", body, timeout)


def verify_seal(seal: dict, api_url: str = DEFAULT_API, timeout: float = 10) -> bool:
    """Verify a seal receipt against the witness ledger.

    GET {api_url}/v1/witness/{seq} and recompute:
      sha256(canonical_json(receipt_payload)) == receipt_sha256
      sha256((prev_hash + receipt_sha256 + ts).encode()) == entry_hash
    Also cross-checks the fetched entry against the seal dict when the
    seal carries witness_seq / receipt_sha256 / entry_hash.
    Returns True only if every check passes; False otherwise.
    """
    if not isinstance(seal, dict):
        return False
    seq = seal.get("witness_seq")
    if seq is None:
        return False
    base = (api_url or DEFAULT_API).rstrip("/")
    try:
        entry = _get_json(f"{base}/v1/witness/{seq}", timeout)
    except SealError:
        return False

    receipt_payload = entry.get("receipt_payload")
    receipt_sha256 = entry.get("receipt_sha256")
    prev_hash = entry.get("prev_hash")
    entry_hash = entry.get("entry_hash")
    ts = entry.get("ts")
    if receipt_payload is None or not receipt_sha256 or prev_hash is None or not entry_hash or ts is None:
        return False

    canonical = json.dumps(receipt_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if hashlib.sha256(canonical).hexdigest() != receipt_sha256:
        return False

    chained = hashlib.sha256((str(prev_hash) + str(receipt_sha256) + str(ts)).encode("utf-8")).hexdigest()
    if chained != entry_hash:
        return False

    # Cross-check against the seal handed to us, when present.
    if seal.get("receipt_sha256") and seal["receipt_sha256"] != receipt_sha256:
        return False
    if seal.get("entry_hash") and seal["entry_hash"] != entry_hash:
        return False
    return True


def _gate(payload: dict, allow_caution: bool) -> dict:
    """Raise on DONT_SIGN / CAUTION per policy. Returns payload on pass."""
    verdict = payload.get("verdict")
    if verdict == "DONT_SIGN":
        raise SealRefused(payload)
    if verdict == "CAUTION" and not allow_caution:
        raise SealCaution(payload)
    if verdict not in ("SIGN", "CAUTION"):
        raise SealError(f"unexpected verdict: {verdict!r} (payload: {payload!r})")
    return payload


class SealedSigner:
    """Drop-in wrapper around a duck-typed signer.

    The wrapped signer may expose any of:
      sign_transaction(tx), sign_message(msg), send_transaction(tx),
      sign_authorization(auth), and optionally .address

    Every signing call is gated by a MAD SEAL verdict first:
      DONT_SIGN            -> SealRefused (signer never called)
      CAUTION (no override)-> SealCaution (signer never called)
      SIGN / CAUTION+flag  -> signer called, returns (result, seal)
    """

    def __init__(
        self,
        signer,
        api_url: str = DEFAULT_API,
        counterparty: dict | None = None,
        caps: dict | None = None,
        allow_caution: bool = False,
        agent_id: int | None = None,
        timeout: float = 10,
        client: str | None = None,
    ):
        self.signer = signer
        self.api_url = api_url
        self.counterparty = counterparty
        self.caps = caps
        self.allow_caution = allow_caution
        self.agent_id = agent_id
        self.timeout = timeout
        self.client = client

    # -- request building -------------------------------------------------

    def _signer_address(self):
        return getattr(self.signer, "address", None)

    def verdict_for_tx(self, tx: dict) -> dict:
        """Build the seal request from a transaction dict and call the API."""
        request: dict = {
            "chainId": tx.get("chainId", 8453),
            "from": tx.get("from") or self._signer_address(),
            "to": tx.get("to"),
            "value": str(tx["value"]) if tx.get("value") is not None else None,
            "data": tx.get("data"),
        }
        if tx.get("submitter"):
            request["submitter"] = tx["submitter"]
        if self.counterparty is not None:
            request["counterparty"] = self.counterparty
        if self.caps is not None:
            request["caps"] = self.caps
        if self.agent_id is not None:
            request["agentId"] = self.agent_id
        if self.client is not None:
            request["client"] = self.client
        # Drop None values so the server sees a clean request.
        request = {k: v for k, v in request.items() if v is not None}
        return seal_verdict(request, api_url=self.api_url, timeout=self.timeout)

    def _verdict_for_authorization(self, auth: dict, counterparty: dict | None = None) -> dict:
        request: dict = {
            "chainId": auth.get("chainId", 8453),
            "from": auth.get("from") or self._signer_address(),
            "to": auth.get("to"),
            "authorization": auth,
            "counterparty": counterparty if counterparty is not None else self.counterparty,
        }
        if self.caps is not None:
            request["caps"] = self.caps
        if self.agent_id is not None:
            request["agentId"] = self.agent_id
        if self.client is not None:
            request["client"] = self.client
        request = {k: v for k, v in request.items() if v is not None}
        return seal_verdict(request, api_url=self.api_url, timeout=self.timeout)

    # -- gated signing ----------------------------------------------------

    def sign_transaction(self, tx: dict):
        """Verdict first, then sign. Returns (signature, seal)."""
        payload = _gate(self.verdict_for_tx(tx), self.allow_caution)
        fn = getattr(self.signer, "sign_transaction", None)
        if fn is None:
            raise SealError("signer has no sign_transaction")
        sig = fn(tx)
        return (sig, payload["seal"])

    def send_transaction(self, tx: dict):
        """Verdict first, then send. Returns (result, seal)."""
        payload = _gate(self.verdict_for_tx(tx), self.allow_caution)
        fn = getattr(self.signer, "send_transaction", None)
        if fn is None:
            raise SealError("signer has no send_transaction")
        result = fn(tx)
        return (result, payload["seal"])

    def sign_authorization(self, auth: dict, counterparty: dict | None = None):
        """Verdict first, then sign an EIP-3009/x402 authorization.

        Returns (signature, seal). Uses signer.sign_authorization if
        present, else signer.sign_message, else raises SealError.
        """
        payload = _gate(
            self._verdict_for_authorization(auth, counterparty=counterparty),
            self.allow_caution,
        )
        seal = payload["seal"]
        if hasattr(self.signer, "sign_authorization"):
            return (self.signer.sign_authorization(auth), seal)
        if hasattr(self.signer, "sign_message"):
            return (self.signer.sign_message(auth), seal)
        raise SealError("signer cannot sign authorizations")

    # -- the settle pair ----------------------------------------------------

    def open_seal(self, intent: dict) -> dict:
        """Open a seal over an intended settlement. Returns the payload.

        intent is an open request dict (see the module-level open_seal);
        this wrapper's counterparty / caps / agent_id / client fill in
        any the intent leaves out. Raises SealRefused when the verdict
        is DONT_SIGN (opened is False) — a seal never opens over what
        the verdict stopped. CAUTION opens: the pair exists to prove
        what settled, caution and all.
        """
        if not isinstance(intent, dict):
            raise SealError("intent must be a dict")
        request = dict(intent)
        if request.get("counterparty") is None and self.counterparty is not None:
            request["counterparty"] = self.counterparty
        if request.get("caps") is None and self.caps is not None:
            request["caps"] = self.caps
        if request.get("agentId") is None and self.agent_id is not None:
            request["agentId"] = self.agent_id
        if request.get("client") is None and self.client is not None:
            request["client"] = self.client
        request = {k: v for k, v in request.items() if v is not None}
        payload = open_seal(request, api_url=self.api_url, timeout=self.timeout)
        if not payload.get("opened") or payload.get("verdict") == "DONT_SIGN":
            raise SealRefused(payload)
        return payload

    def close_seal(self, seal_id: str, tx_hash: str, chain_id: int | None = None) -> dict:
        """Close an opened seal against the settlement tx that landed.

        Returns the close payload (outcome SEALED or DRIFT, reasons,
        deltas, expected vs actual, open_seq / close_seq, seal).
        DRIFT is a result, not an exception — read the payload.
        """
        return close_seal(
            seal_id,
            tx_hash,
            chain_id=chain_id,
            api_url=self.api_url,
            timeout=max(self.timeout, 30),
        )

    def settle(self, intent: dict, settle_fn) -> dict:
        """The full pair around a caller-supplied settlement.

        Opens a seal over intent, calls settle_fn(intent) -> tx_hash
        (the caller's own code performs and broadcasts the settlement;
        MAD never signs or sends), then closes the seal against that
        tx hash and returns the close payload. If the open verdict is
        DONT_SIGN, SealRefused raises before settle_fn is ever called.
        """
        opened = self.open_seal(intent)
        tx_hash = settle_fn(intent)
        if not tx_hash:
            raise SealError("settle_fn returned no tx hash")
        return self.close_seal(
            opened["seal_id"], tx_hash, chain_id=intent.get("chainId")
        )
