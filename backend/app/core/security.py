import hashlib
import hmac

from fastapi import HTTPException, Request, status

from backend.app.core.config import get_settings

GLOBAL_VIEWER_ROLES = {"admin", "dev", "dev-admin"}


def verify_api_key(request: Request) -> None:
    """Optional API key gate for enterprise deployments.

    Development keeps this disabled by default. Set REQUIRE_API_KEY=true and
    API_KEYS=key1,key2 to protect business endpoints.
    """

    settings = get_settings()
    if not settings.require_api_key:
        request.state.actor_role = "dev"
        request.state.actor_hash = "auth-disabled"
        return

    trusted_actor = _trusted_proxy_actor(request)
    if trusted_actor:
        request.state.actor_role, request.state.actor_hash = trusted_actor
        return

    if not settings.has_any_api_key_material:
        if settings.trusted_proxy_auth_enabled:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing API key or trusted proxy identity",
                headers={"WWW-Authenticate": "ApiKey"},
            )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API key authentication is enabled but API_KEYS/API_KEY_HASHES are empty",
        )

    provided_key = _extract_api_key(request)
    if not provided_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    if not _matches_any_user_or_admin_key(provided_key):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid API key")

    role = "admin" if _matches_admin_key(provided_key) else "user"
    request.state.actor_role = role
    request.state.actor_hash = _hash_key(provided_key)


def verify_admin_api_key(request: Request) -> None:
    """Require an admin API key for mutation, debug, and observability endpoints."""

    settings = get_settings()
    if not settings.require_api_key:
        request.state.actor_role = "dev-admin"
        request.state.actor_hash = "auth-disabled"
        return

    trusted_actor = _trusted_proxy_actor(request)
    if trusted_actor:
        actor_role, actor_hash = trusted_actor
        if actor_role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Trusted proxy admin role required",
            )
        request.state.actor_role = actor_role
        request.state.actor_hash = actor_hash
        return

    if not settings.has_admin_api_key_material:
        if settings.trusted_proxy_auth_enabled:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing admin API key or trusted proxy admin identity",
                headers={"WWW-Authenticate": "ApiKey"},
            )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Admin authentication is enabled but ADMIN_API_KEYS/ADMIN_API_KEY_HASHES are empty"
            ),
        )

    provided_key = _extract_api_key(request)
    if not provided_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing admin API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    if not _matches_admin_key(provided_key):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin API key required")

    request.state.actor_role = "admin"
    request.state.actor_hash = _hash_key(provided_key)


def _extract_api_key(request: Request) -> str:
    provided_key = request.headers.get("x-api-key", "")
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        provided_key = authorization.split(" ", maxsplit=1)[1].strip()
    return provided_key


def _trusted_proxy_actor(request: Request) -> tuple[str, str] | None:
    settings = get_settings()
    if not settings.trusted_proxy_auth_enabled:
        return None

    provided_secret = request.headers.get(settings.trusted_proxy_secret_header, "")
    if not provided_secret:
        return None

    configured_secret = settings.trusted_proxy_auth_secret.strip()
    if not configured_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Trusted proxy authentication is enabled but the shared secret is empty",
        )
    if not hmac.compare_digest(provided_secret, configured_secret):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid trusted proxy secret",
        )

    user_id = request.headers.get(settings.trusted_proxy_user_header, "").strip()
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing trusted proxy user identity",
        )

    role = request.headers.get(settings.trusted_proxy_role_header, "user").strip().lower()
    if role not in {"user", "admin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Trusted proxy role must be user or admin",
        )
    return role, _hash_trusted_identity(user_id)


def _matches_any(provided_key: str, configured_keys: list[str]) -> bool:
    return any(hmac.compare_digest(provided_key, key) for key in configured_keys)


def _matches_any_hash(provided_key: str, configured_hashes: list[str]) -> bool:
    provided_hash = hashlib.sha256(provided_key.encode("utf-8")).hexdigest()
    return any(hmac.compare_digest(provided_hash, key_hash) for key_hash in configured_hashes)


def _matches_admin_key(provided_key: str) -> bool:
    settings = get_settings()
    return _matches_any(provided_key, settings.parsed_admin_api_keys) or _matches_any_hash(
        provided_key,
        settings.parsed_admin_api_key_hashes,
    )


def _matches_any_user_or_admin_key(provided_key: str) -> bool:
    settings = get_settings()
    return _matches_any(provided_key, settings.parsed_all_api_keys) or _matches_any_hash(
        provided_key,
        [*settings.parsed_api_key_hashes, *settings.parsed_admin_api_key_hashes],
    )


def _hash_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]


def _hash_trusted_identity(user_id: str) -> str:
    return f"proxy_{hashlib.sha256(user_id.encode('utf-8')).hexdigest()[:16]}"


def request_actor(request: Request) -> tuple[str, str]:
    return (
        getattr(request.state, "actor_role", "anonymous"),
        getattr(request.state, "actor_hash", "none"),
    )


def can_view_owned_resource(requester_role: str, requester_hash: str, owner_hash: str) -> bool:
    if requester_role in GLOBAL_VIEWER_ROLES or requester_hash == "auth-disabled":
        return True
    return requester_hash == owner_hash
