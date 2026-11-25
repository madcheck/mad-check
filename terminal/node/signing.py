#!/usr/bin/env python3
"""Pure-stdlib signing for the MAD node: keccak-256 + secp256k1 + EIP-191.

The terminal ships as a .deb for operators' own machines, where the
system python3 has no eth_account (the MAD watch venv has it; the
operator's box does not). A node that cannot sign without a venv is
a node that cannot sign at all — so the crypto lives here, in plain
Python, stdlib only: Keccak-f[1600], secp256k1, RFC 6979
deterministic k, EIP-191 personal_sign.

What it produces is exactly what eth_account produces for the same
key and message: a 65-byte (r, s, v) signature over
keccak("\\x19Ethereum Signed Message:\\n" + len + msg). Any third
agent verifies it with eth_account (or any EIP-191 verifier) without
trusting the messenger: recover the signer from the signature and
compare it to the claimed signer. The cross-check against
eth_account is in the selftest notes, not in this file — this file
must run where eth_account does not exist.

A signature is a message signature, never a transaction. Nothing
here signs, sends, or moves value. The operator key is read from
MAD_OPERATOR_KEY_FILE / MAD_OPERATOR_KEY, or
~/.config/mad-terminal/operator-key.json (0600). The terminal never
generates a key unprompted and never writes one anywhere.
"""
import hashlib
import hmac
import json
import os

# ------------------------------------------------------------------ keccak --

# Keccak-f[1600] round constants.
_RC = [
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A,
    0x8000000080008000, 0x000000000000808B, 0x0000000080000001,
    0x8000000080008081, 0x8000000000008009, 0x000000000000008A,
    0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089,
    0x8000000000008003, 0x8000000000008002, 0x8000000000000080,
    0x000000000000800A, 0x800000008000000A, 0x8000000080008081,
    0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
]
# Rotation offsets, indexed [x][y].
_R = [
    [0, 36, 3, 41, 18],
    [1, 44, 10, 45, 2],
    [62, 6, 43, 15, 61],
    [28, 55, 25, 21, 56],
    [27, 20, 39, 8, 14],
]
_MASK = (1 << 64) - 1


def _rol(x, n):
    return ((x << n) | (x >> (64 - n))) & _MASK if n else x


def _keccak_f(state):
    """Keccak-f[1600] on a 25-lane state (lane i = x + 5*y)."""
    for rnd in range(24):
        # Theta
        c = [state[x] ^ state[x + 5] ^ state[x + 10] ^ state[x + 15]
             ^ state[x + 20] for x in range(5)]
        for x in range(5):
            d = c[(x + 4) % 5] ^ _rol(c[(x + 1) % 5], 1)
            for y in range(5):
                state[x + 5 * y] ^= d
        # Rho + Pi
        b = [0] * 25
        for x in range(5):
            for y in range(5):
                b[y + 5 * ((2 * x + 3 * y) % 5)] = _rol(
                    state[x + 5 * y], _R[x][y])
        # Chi
        for x in range(5):
            for y in range(5):
                state[x + 5 * y] = (b[x + 5 * y]
                                    ^ ((~b[((x + 1) % 5) + 5 * y])
                                       & b[((x + 2) % 5) + 5 * y]))
        # Iota
        state[0] ^= _RC[rnd]
    return state


def keccak256(data):
    """keccak-256 (the original Keccak padding 0x01, NOT SHA3-256)."""
    if isinstance(data, str):
        data = data.encode()
    # rate 1088 bits = 136 bytes; suffix 0x01, final bit 0x80.
    state = [0] * 25
    block = 136
    off = 0
    while len(data) - off >= block:
        chunk = data[off:off + block]
        for i in range(block // 8):
            state[i] ^= int.from_bytes(chunk[i * 8:(i + 1) * 8], "little")
        _keccak_f(state)
        off += block
    tail = bytearray(data[off:])
    tail.append(0x01)
    tail += b"\x00" * (block - len(tail))
    tail[-1] |= 0x80
    for i in range(block // 8):
        state[i] ^= int.from_bytes(tail[i * 8:(i + 1) * 8], "little")
    _keccak_f(state)
    out = b"".join(state[i].to_bytes(8, "little") for i in range(4))
    return out


# ---------------------------------------------------------------- secp256k1 --

P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
Gx = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
Gy = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8
G = (Gx, Gy)


def _inv(a, m):
    return pow(a % m, -1, m)


def _point_add(p1, p2):
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2 and (y1 + y2) % P == 0:
        return None
    if p1 == p2:
        lam = (3 * x1 * x1) * _inv(2 * y1, P) % P
    else:
        lam = (y2 - y1) * _inv(x2 - x1, P) % P
    x3 = (lam * lam - x1 - x2) % P
    return (x3, (lam * (x1 - x3) - y1) % P)


def _scalar_mult(k, point=G):
    out = None
    add = point
    while k:
        if k & 1:
            out = _point_add(out, add)
        add = _point_add(add, add)
        k >>= 1
    return out


def privkey_to_address(priv):
    """0x address for a 32-byte private key (int or hex)."""
    if isinstance(priv, str):
        priv = int(priv.removeprefix("0x"), 16)
    q = _scalar_mult(priv)
    digest = keccak256(q[0].to_bytes(32, "big") + q[1].to_bytes(32, "big"))
    return "0x" + digest[-20:].hex()


def _rfc6979_k(priv_bytes, h1):
    """Deterministic k (RFC 6979, HMAC-SHA256)."""
    bx = priv_bytes + h1
    v = b"\x01" * 32
    k = b"\x00" * 32
    k = hmac.new(k, v + b"\x00" + bx, hashlib.sha256).digest()
    v = hmac.new(k, v, hashlib.sha256).digest()
    k = hmac.new(k, v + b"\x01" + bx, hashlib.sha256).digest()
    v = hmac.new(k, v, hashlib.sha256).digest()
    while True:
        v = hmac.new(k, v, hashlib.sha256).digest()
        cand = int.from_bytes(v, "big")
        if 1 <= cand < N:
            return cand
        k = hmac.new(k, v + b"\x00", hashlib.sha256).digest()
        v = hmac.new(k, v, hashlib.sha256).digest()


def _decompress(x, odd):
    y2 = (pow(x, 3, P) + 7) % P
    y = pow(y2, (P + 1) // 4, P)
    if (y & 1) != odd:
        y = P - y
    return (x, y)


def sign_hash(msg_hash, priv):
    """Sign a 32-byte hash (already the EIP-191 digest). Returns the
    65-byte signature (r || s || v, v in 27/28). Low-s enforced."""
    if isinstance(priv, str):
        priv = int(priv.removeprefix("0x"), 16)
    z = int.from_bytes(msg_hash, "big")
    k = _rfc6979_k(priv.to_bytes(32, "big"), msg_hash)
    r_point = _scalar_mult(k)
    r = r_point[0] % N
    recid = (r_point[1] & 1) | (2 if r_point[0] >= N else 0)
    s = (_inv(k, N) * (z + r * priv)) % N
    if s > N // 2:
        s = N - s
        recid ^= 1
    return r.to_bytes(32, "big") + s.to_bytes(32, "big") + bytes([27 + recid])


def eip191_hash(message):
    """keccak of the EIP-191 personal_sign envelope for a message."""
    if isinstance(message, str):
        message = message.encode()
    prefix = b"\x19Ethereum Signed Message:\n" + str(len(message)).encode()
    return keccak256(prefix + message)


def sign_message(message, priv):
    """EIP-191 personal_sign. Returns (signature_bytes, signer)."""
    digest = eip191_hash(message)
    return sign_hash(digest, priv), privkey_to_address(priv)


def recover_address(msg_hash, sig):
    """Recover the signer address from a 32-byte hash + 65-byte sig."""
    if len(sig) != 65:
        raise ValueError("signature must be 65 bytes")
    r = int.from_bytes(sig[0:32], "big")
    s = int.from_bytes(sig[32:64], "big")
    v = sig[64]
    if v >= 27:
        v -= 27
    if v not in (0, 1, 2, 3) or not (1 <= r < N) or not (1 <= s < N):
        raise ValueError("bad signature")
    z = int.from_bytes(msg_hash, "big")
    x = r + (v // 2) * N
    if x >= P:
        raise ValueError("bad signature: x out of range")
    r_point = _decompress(x, v & 1)
    r_inv = _inv(r, N)
    q = _point_add(_scalar_mult(s * r_inv % N, r_point),
                   _scalar_mult((-z * r_inv) % N))
    if q is None:
        raise ValueError("bad signature: recovered infinity")
    digest = keccak256(q[0].to_bytes(32, "big") + q[1].to_bytes(32, "big"))
    return "0x" + digest[-20:].hex()


def verify_message(message, sig, expected_signer):
    """True iff the signature over the message recovers the expected
    signer. This is the whole of portable verification: a third
    agent needs only the message, the signature, and the claimed
    signer — never the messenger."""
    try:
        return recover_address(eip191_hash(message), sig).lower() \
            == expected_signer.lower()
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------- operator key --

def load_operator_key():
    """The operator's signing key, or None. Sources, in order:
    MAD_OPERATOR_KEY (hex), MAD_OPERATOR_KEY_FILE (a JSON file with
    a private_key field, like ~/.secrets/mad_wallet.json),
    ~/.config/mad-terminal/operator-key.json. Never generated here,
    never written here, never printed."""
    raw = os.environ.get("MAD_OPERATOR_KEY", "").strip()
    if raw:
        return raw
    path = os.environ.get("MAD_OPERATOR_KEY_FILE", "").strip()
    if not path:
        path = os.path.join(os.path.expanduser("~"), ".config",
                            "mad-terminal", "operator-key.json")
    try:
        with open(path) as f:
            data = json.load(f)
        pk = data.get("private_key") or data.get("privateKey")
        if pk:
            return pk
    except (OSError, ValueError):
        pass
    return None


def operator_address():
    """The configured operator's address, or None."""
    pk = load_operator_key()
    if not pk:
        return None
    try:
        return privkey_to_address(pk)
    except (ValueError, TypeError):
        return None


# ------------------------------------------------------------------ selftest --

def selftest():
    ok = True

    def check(label, cond, detail):
        nonlocal ok
        print("  [%s] %s: %s" % ("PASS" if cond else "FAIL", label, detail))
        ok = ok and cond

    print("== signing selftest (pure stdlib) ==")
    check("keccak256('')",
          keccak256(b"").hex() == "c5d2460186f7233c927e7db2dcc703c0e500b6"
          "53ca82273b7bfad8045d85a470",
          keccak256(b"").hex()[:16] + "...")
    check("keccak256('hello')",
          keccak256(b"hello").hex() == "1c8aff950685c2ed4bc3174f3472287"
          "b56d9517b9c948127319a09a7a36deac8",
          keccak256(b"hello").hex()[:16] + "...")
    check("keccak256('abc')",
          keccak256(b"abc").hex() == "4e03657aea45a94fc7d47ba826c8d667"
          "c0d1e6e33a64a036ec44f58fa12d6c45",
          keccak256(b"abc").hex()[:16] + "...")
    # Known key: 0x01 -> the well-known first address.
    check("privkey 0x01 address",
          privkey_to_address(1) == "0x7e5f4552091a69125d5dfcb7b8c2659029395bdf",
          privkey_to_address(1))
    # Round trip: sign, recover, verify — and the signature is
    # deterministic (RFC 6979), so the same message signs the same.
    msg = "MAD node verdict: robinhood block 122000000 PASS"
    sig1, signer = sign_message(msg, 1)
    sig2, _ = sign_message(msg, 1)
    check("signing is deterministic (RFC 6979)", sig1 == sig2,
          sig1.hex()[:20] + "...")
    check("recovery returns the signer",
          recover_address(eip191_hash(msg), sig1) == signer, signer)
    check("verify_message accepts the true signer",
          verify_message(msg, sig1, signer), "true")
    check("verify_message rejects a wrong signer",
          not verify_message(msg, sig1,
                             "0x0000000000000000000000000000000000000000"),
          "false")
    check("verify_message rejects a tampered message",
          not verify_message(msg + "!", sig1, signer), "false")
    # A second key, arbitrary bytes, same round trip.
    pk2 = "0x" + "deadbeef" * 8
    sig3, signer3 = sign_message("second key, second message", pk2)
    check("second key round-trips",
          verify_message("second key, second message", sig3, signer3),
          signer3)
    print("== signing selftest", "PASS ==" if ok else "FAIL ==")
    return 0 if ok else 1


if __name__ == "__main__":
    import sys
    sys.exit(selftest())
