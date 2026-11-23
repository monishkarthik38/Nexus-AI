"""Supabase JWT validation and development-only local identity."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import jwt
from fastapi import Header, HTTPException, status
import httpx

from app.config import settings


@dataclass(frozen=True)
class CurrentUser:
    id: str
    email: str | None = None


_jwks_cache: dict[str, Any] = {"expires_at": 0.0, "url": None, "keys": []}


async def _get_jwks() -> list[dict[str, Any]]:
    now = time.monotonic()
    if _jwks_cache["expires_at"] > now and _jwks_cache["url"] == settings.SUPABASE_URL:
        return _jwks_cache["keys"]

    if not settings.SUPABASE_URL:
        raise HTTPException(status_code=503, detail="Supabase authentication is not configured")

    url = f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1/.well-known/jwks.json"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            keys = response.json().get("keys", [])
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="Could not load authentication signing keys") from exc

    _jwks_cache.update({"expires_at": now + 300, "url": settings.SUPABASE_URL, "keys": keys})
    return keys


async def _verify_supabase_token(token: str) -> CurrentUser:
    if not settings.SUPABASE_URL:
        raise HTTPException(status_code=503, detail="Supabase authentication is not configured")

    try:
        header = jwt.get_unverified_header(token)
        algorithm = header.get("alg")
        issuer = f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1"
        if algorithm in {"ES256", "RS256"}:
            kid = header.get("kid")
            jwk = next((key for key in await _get_jwks() if key.get("kid") == kid), None)
            if jwk is None:
                _jwks_cache["expires_at"] = 0
                jwk = next((key for key in await _get_jwks() if key.get("kid") == kid), None)
            if jwk is None:
                raise ValueError("No matching signing key")
            signing_key = jwt.PyJWK.from_dict(jwk, algorithm=algorithm).key
            payload = jwt.decode(token, signing_key, algorithms=[algorithm], audience="authenticated", issuer=issuer)
        elif algorithm == "HS256" and settings.SUPABASE_JWT_SECRET:
            payload = jwt.decode(token, settings.SUPABASE_JWT_SECRET, algorithms=["HS256"], audience="authenticated", issuer=issuer)
        else:
            raise ValueError("Unsupported JWT signing algorithm")

        subject = payload.get("sub")
        if not isinstance(subject, str) or not subject:
            raise ValueError("JWT is missing subject")
        return CurrentUser(id=subject, email=payload.get("email"))
    except HTTPException:
        raise
    except (jwt.PyJWTError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired access token", headers={"WWW-Authenticate": "Bearer"}) from exc


async def get_current_user(authorization: str | None = Header(default=None), x_dev_user: str | None = Header(default=None)) -> CurrentUser:
    """Resolve a verified user. X-Dev-User is honored only in local development."""
    if settings.AUTH_MODE == "development":
        return CurrentUser(id=x_dev_user or settings.DEVELOPMENT_USER_ID)

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer access token required", headers={"WWW-Authenticate": "Bearer"})
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer access token required", headers={"WWW-Authenticate": "Bearer"})
    return await _verify_supabase_token(token)
