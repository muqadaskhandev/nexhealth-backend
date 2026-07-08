"""Config-driven OpenID Connect (OAuth2 authorization-code + PKCE) for SSO.

One generic OIDC client drives Google, Azure (Microsoft), and Okta. Each
provider is described by an OIDC discovery document, from which we read the
authorization/token/JWKS endpoints. The flow is:

  1. begin_login()  -> build the provider authorize URL with state + PKCE
                       challenge, and a signed "transaction" JWT that carries
                       the state, nonce and code_verifier back to the callback.
  2. complete_login()-> verify state, exchange the code (with code_verifier),
                       verify the id_token signature (JWKS), aud, iss & nonce,
                       and return the verified claims (email, name).

Security properties: PKCE defeats code interception, `state` defeats CSRF on the
callback, `nonce` binds the id_token to this transaction, and the id_token
signature/issuer/audience are all verified before we trust any claim.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
import jwt
from jwt import PyJWKClient

from app.config import settings

_TX_TTL_SECONDS = 600  # 10 minutes to complete the round-trip
_TX_TYPE = "oauth_tx"


class OAuthError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    client_id: str
    client_secret: str
    discovery_url: str
    scopes: str = "openid email profile"

    @property
    def enabled(self) -> bool:
        return bool(self.client_id and self.client_secret and self.discovery_url)


def _providers() -> dict[str, ProviderConfig]:
    okta_domain = settings.okta_domain.rstrip("/")
    return {
        "google": ProviderConfig(
            name="google",
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            discovery_url="https://accounts.google.com/.well-known/openid-configuration",
        ),
        "azure": ProviderConfig(
            name="azure",
            client_id=settings.azure_client_id,
            client_secret=settings.azure_client_secret,
            discovery_url=(
                f"https://login.microsoftonline.com/{settings.azure_tenant_id}"
                "/v2.0/.well-known/openid-configuration"
            ),
        ),
        "okta": ProviderConfig(
            name="okta",
            client_id=settings.okta_client_id,
            client_secret=settings.okta_client_secret,
            discovery_url=(
                f"{okta_domain}/.well-known/openid-configuration" if okta_domain else ""
            ),
        ),
    }


def get_provider(name: str) -> ProviderConfig:
    provider = _providers().get(name)
    if provider is None:
        raise OAuthError(f"Unknown SSO provider '{name}'")
    if not provider.enabled:
        raise OAuthError(f"SSO provider '{name}' is not configured")
    return provider


def enabled_providers() -> dict[str, bool]:
    return {name: p.enabled for name, p in _providers().items()}


# ── Discovery (cached in-process) ────────────────────────────────────────────
_discovery_cache: dict[str, dict] = {}
_jwks_cache: dict[str, PyJWKClient] = {}


async def _discover(provider: ProviderConfig) -> dict:
    if provider.discovery_url not in _discovery_cache:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(provider.discovery_url)
            resp.raise_for_status()
            _discovery_cache[provider.discovery_url] = resp.json()
    return _discovery_cache[provider.discovery_url]


def _jwk_client(jwks_uri: str) -> PyJWKClient:
    if jwks_uri not in _jwks_cache:
        _jwks_cache[jwks_uri] = PyJWKClient(jwks_uri, cache_keys=True)
    return _jwks_cache[jwks_uri]


def redirect_uri(provider_name: str) -> str:
    return f"{settings.backend_url.rstrip('/')}/api/auth/sso/{provider_name}/callback"


# ── PKCE helpers ─────────────────────────────────────────────────────────────
def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


# ── Transaction token (state carrier) ────────────────────────────────────────
def _encode_tx(provider: str, state: str, nonce: str, verifier: str) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "type": _TX_TYPE,
            "provider": provider,
            "state": state,
            "nonce": nonce,
            "cv": verifier,
            "iat": now,
            "exp": now + _TX_TTL_SECONDS,
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def _decode_tx(token: str) -> dict:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "state"]},
        )
    except jwt.PyJWTError as exc:
        raise OAuthError("SSO transaction expired or invalid") from exc
    if payload.get("type") != _TX_TYPE:
        raise OAuthError("Invalid SSO transaction")
    return payload


@dataclass
class LoginStart:
    authorize_url: str
    tx_token: str


@dataclass
class OidcIdentity:
    provider: str
    email: str
    email_verified: bool
    first_name: str
    last_name: str


async def begin_login(provider_name: str) -> LoginStart:
    provider = get_provider(provider_name)
    disc = await _discover(provider)

    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    verifier, challenge = _pkce_pair()

    params = {
        "response_type": "code",
        "client_id": provider.client_id,
        "redirect_uri": redirect_uri(provider_name),
        "scope": provider.scopes,
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    authorize_url = f"{disc['authorization_endpoint']}?{urlencode(params)}"
    tx = _encode_tx(provider_name, state, nonce, verifier)
    return LoginStart(authorize_url=authorize_url, tx_token=tx)


async def complete_login(
    *, tx_token: str, returned_state: str, code: str
) -> OidcIdentity:
    tx = _decode_tx(tx_token)
    if not secrets.compare_digest(tx["state"], returned_state):
        raise OAuthError("SSO state mismatch")

    provider = get_provider(tx["provider"])
    disc = await _discover(provider)

    # Exchange the authorization code for tokens.
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri(provider.name),
        "client_id": provider.client_id,
        "client_secret": provider.client_secret,
        "code_verifier": tx["cv"],
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            disc["token_endpoint"],
            data=data,
            headers={"Accept": "application/json"},
        )
    if resp.status_code != 200:
        raise OAuthError("Failed to exchange authorization code")
    tokens = resp.json()
    id_token = tokens.get("id_token")
    if not id_token:
        raise OAuthError("Provider did not return an id_token")

    claims = _verify_id_token(
        id_token=id_token,
        jwks_uri=disc["jwks_uri"],
        issuer=disc["issuer"],
        audience=provider.client_id,
        expected_nonce=tx["nonce"],
    )

    email = (claims.get("email") or claims.get("preferred_username") or "").strip().lower()
    if not email:
        raise OAuthError("Provider did not return an email address")

    given = claims.get("given_name", "")
    family = claims.get("family_name", "")
    if not given and not family and claims.get("name"):
        parts = str(claims["name"]).split(" ", 1)
        given = parts[0]
        family = parts[1] if len(parts) > 1 else ""

    return OidcIdentity(
        provider=provider.name,
        email=email,
        email_verified=bool(claims.get("email_verified", True)),
        first_name=given,
        last_name=family,
    )


def _verify_id_token(
    *, id_token: str, jwks_uri: str, issuer: str, audience: str, expected_nonce: str
) -> dict:
    signing_key = _jwk_client(jwks_uri).get_signing_key_from_jwt(id_token)
    try:
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=audience,
            issuer=issuer,
            options={"require": ["exp", "iat", "aud", "iss"]},
        )
    except jwt.PyJWTError as exc:
        raise OAuthError("id_token verification failed") from exc

    if expected_nonce and claims.get("nonce") != expected_nonce:
        raise OAuthError("id_token nonce mismatch")
    return claims
