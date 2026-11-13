"""The key the router signs OpenID Connect ID tokens with (ADR 0094).

`VCR_OAUTH_SIGNING_KEY` holds one PEM private key: RSA (RS256) or EC P-256 (ES256). The
value may also be the PEM base64-encoded on one line, for secret stores that mangle
newlines. Only the public half leaves the router, through the JWKS.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

OAUTH_SIGNING_KEY_ENV = "VCR_OAUTH_SIGNING_KEY"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _uint(value: int, length: int | None = None) -> str:
    size = length or max(1, (value.bit_length() + 7) // 8)
    return _b64url(value.to_bytes(size, "big"))


@dataclass(frozen=True)
class OAuthSigningKey:
    private_key: rsa.RSAPrivateKey | ec.EllipticCurvePrivateKey
    alg: str
    kid: str
    public_jwk: dict[str, str]

    def jwks(self) -> dict[str, Any]:
        return {"keys": [dict(self.public_jwk)]}

    def sign_jwt(self, claims: dict[str, Any]) -> str:
        header = {"alg": self.alg, "typ": "JWT", "kid": self.kid}
        signing_input = (
            _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
            + "."
            + _b64url(json.dumps(claims, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
        )
        data = signing_input.encode("ascii")
        if isinstance(self.private_key, rsa.RSAPrivateKey):
            signature = self.private_key.sign(data, padding.PKCS1v15(), hashes.SHA256())
        else:
            r, s = decode_dss_signature(self.private_key.sign(data, ec.ECDSA(hashes.SHA256())))
            signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
        return f"{signing_input}.{_b64url(signature)}"


def _thumbprint(required: dict[str, str]) -> str:
    """RFC 7638 JWK thumbprint, used as the key id."""
    canonical = json.dumps(required, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return _b64url(hashlib.sha256(canonical).digest())


def signing_key_from_private_key(
    private_key: rsa.RSAPrivateKey | ec.EllipticCurvePrivateKey,
) -> OAuthSigningKey:
    if isinstance(private_key, rsa.RSAPrivateKey):
        if private_key.key_size < 2048:
            raise ValueError(f"{OAUTH_SIGNING_KEY_ENV} RSA key must be at least 2048 bits")
        numbers = private_key.public_key().public_numbers()
        required = {"e": _uint(numbers.e), "kty": "RSA", "n": _uint(numbers.n)}
        alg = "RS256"
    elif isinstance(private_key, ec.EllipticCurvePrivateKey) and isinstance(
        private_key.curve, ec.SECP256R1
    ):
        numbers = private_key.public_key().public_numbers()
        required = {"crv": "P-256", "kty": "EC", "x": _uint(numbers.x, 32), "y": _uint(numbers.y, 32)}
        alg = "ES256"
    else:
        raise ValueError(f"{OAUTH_SIGNING_KEY_ENV} must be an RSA or EC P-256 private key")
    kid = _thumbprint(required)
    return OAuthSigningKey(
        private_key=private_key,
        alg=alg,
        kid=kid,
        public_jwk={**required, "alg": alg, "use": "sig", "kid": kid},
    )


def load_oauth_signing_key(raw: str) -> OAuthSigningKey:
    """Parse a PEM (or base64 PEM) private key. Anything unreadable raises ValueError."""
    text = (raw or "").strip()
    if not text:
        raise ValueError(f"{OAUTH_SIGNING_KEY_ENV} is empty")
    if not text.startswith("-----BEGIN"):
        try:
            text = base64.b64decode(text, validate=True).decode("ascii").strip()
        except (binascii.Error, UnicodeDecodeError) as exc:
            raise ValueError(f"{OAUTH_SIGNING_KEY_ENV} is neither PEM nor base64 PEM") from exc
    try:
        private_key = serialization.load_pem_private_key(text.encode("ascii"), password=None)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{OAUTH_SIGNING_KEY_ENV} is not a readable unencrypted private key") from exc
    if not isinstance(private_key, (rsa.RSAPrivateKey, ec.EllipticCurvePrivateKey)):
        raise ValueError(f"{OAUTH_SIGNING_KEY_ENV} must be an RSA or EC P-256 private key")
    return signing_key_from_private_key(private_key)


def development_signing_key() -> OAuthSigningKey:
    """A key made at start for local development; ID tokens die with the process."""
    return signing_key_from_private_key(rsa.generate_private_key(public_exponent=65537, key_size=2048))


def oauth_signing_key_from_environment(
    raw: str | None,
    *,
    production: bool,
    clients_registered: bool,
) -> OAuthSigningKey | None:
    """The signing key the router serves with.

    Set: parsed, and a malformed value refuses to start anywhere. Unset outside
    production: a development key made at start. Unset in production: refuses to start
    when any OAuth Client is registered, otherwise the authorization server stays off.
    """
    if raw is not None and raw.strip() != "":
        return load_oauth_signing_key(raw)
    if not production:
        return development_signing_key()
    if clients_registered:
        raise ValueError(
            f"{OAUTH_SIGNING_KEY_ENV} is required in production when oauth.clients is configured"
        )
    return None
