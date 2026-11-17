import hashlib
import hmac
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

from app.config import settings
from app.database import get_database

logger = logging.getLogger("kagazastra.auth")

SESSION_COOKIE = "kagazastra_session"
SESSION_TTL = timedelta(days=7)
PASSWORD_ITERATIONS = 310_000
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

auth_router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=100)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=10, max_length=256)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


def _database():
    database = get_database()
    if database is None:
        raise HTTPException(status_code=503, detail="Account service is unavailable. Check MongoDB.")
    return database


def _normalize_email(email: str) -> str:
    normalized = email.strip().casefold()
    if not EMAIL_PATTERN.fullmatch(normalized):
        raise HTTPException(status_code=422, detail="Enter a valid email address.")
    return normalized


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_ITERATIONS,
    )
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def _verify_password(password: str, stored_hash: str | None) -> bool:
    if not stored_hash:
        return False
    try:
        algorithm, iteration_text, salt_hex, digest_hex = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iteration_text)
        if not 100_000 <= iterations <= 2_000_000:
            return False
        candidate = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            iterations,
        )
        return hmac.compare_digest(candidate.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


_DUMMY_PASSWORD_HASH = _hash_password("constant-time account lookup check")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _public_user(user: dict[str, Any]) -> dict[str, Any]:
    created_at = user.get("created_at")
    return {
        "id": user["id"],
        "full_name": user["full_name"],
        "email": user["email"],
        "role": user["role"],
        "active": user["active"],
        "created_at": created_at.isoformat() if created_at else None,
    }


async def _create_session(database, user: dict[str, Any]) -> tuple[str, str]:
    raw_token = secrets.token_urlsafe(48)
    csrf_token = secrets.token_urlsafe(32)
    await database.sessions.insert_one(
        {
            "token_hash": _token_hash(raw_token),
            "csrf_token": csrf_token,
            "user_id": user["id"],
            "expires_at": datetime.now(timezone.utc) + SESSION_TTL,
            "created_at": datetime.now(timezone.utc),
        }
    )
    return raw_token, csrf_token


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True,
        secure=settings.SESSION_COOKIE_SECURE or settings.APP_ENV.casefold() == "production",
        samesite="lax",
        path="/",
    )


async def initialize_auth(database) -> None:
    await database.users.create_index("id", unique=True)
    await database.users.create_index("email", unique=True)
    await database.sessions.create_index("token_hash", unique=True)
    await database.sessions.create_index("expires_at", expireAfterSeconds=0)
    await database.payments.create_index("transaction_id", unique=True, sparse=True)
    await database.usage.create_index([("user_id", 1), ("created_at", -1)])

    admin_email_setting = settings.ADMIN_EMAIL.strip()
    admin_password = settings.ADMIN_PASSWORD.get_secret_value()
    if not admin_email_setting and not admin_password:
        logger.warning("Admin account is not configured; set ADMIN_EMAIL and ADMIN_PASSWORD in .env.")
        return
    if not admin_email_setting or not admin_password:
        raise RuntimeError("Set both ADMIN_EMAIL and ADMIN_PASSWORD to configure the admin account.")

    if not EMAIL_PATTERN.fullmatch(admin_email_setting.casefold()):
        raise RuntimeError("ADMIN_EMAIL must be a valid email address.")
    admin_email = admin_email_setting.casefold()
    if len(admin_password) < 16:
        raise RuntimeError("ADMIN_PASSWORD must contain at least 16 characters.")

    now = datetime.now(timezone.utc)
    await database.users.update_one(
        {"email": admin_email},
        {
            "$set": {
                "full_name": "Administrator",
                "email": admin_email,
                "password_hash": _hash_password(admin_password),
                "role": "admin",
                "active": True,
            },
            "$setOnInsert": {
                "id": secrets.token_hex(16),
                "created_at": now,
            },
        },
        upsert=True,
    )
    logger.info("Admin account bootstrapped from ADMIN_EMAIL.")


async def get_optional_user(request: Request) -> dict[str, Any] | None:
    raw_token = request.cookies.get(SESSION_COOKIE)
    if not raw_token:
        return None

    database = _database()
    session = await database.sessions.find_one(
        {
            "token_hash": _token_hash(raw_token),
            "expires_at": {"$gt": datetime.now(timezone.utc)},
        }
    )
    if session is None:
        raise HTTPException(status_code=401, detail="Session expired. Please sign in again.")

    user = await database.users.find_one({"id": session["user_id"]})
    if user is None or not user.get("active", False):
        await database.sessions.delete_one({"token_hash": session["token_hash"]})
        raise HTTPException(status_code=403, detail="This account is suspended or unavailable.")

    request.state.auth_session = session
    return user


async def get_current_user(
    user: dict[str, Any] | None = Depends(get_optional_user),
) -> dict[str, Any]:
    if user is None:
        raise HTTPException(status_code=401, detail="Please sign in to continue.")
    return user


async def require_client(
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    if user["role"] != "client":
        raise HTTPException(status_code=403, detail="This page is for client accounts.")
    return user


async def require_admin(
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Administrator access is required.")
    return user


async def require_csrf(
    request: Request,
    csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    session = getattr(request.state, "auth_session", None)
    expected = session.get("csrf_token") if session else None
    if not csrf_token or not expected or not hmac.compare_digest(csrf_token, expected):
        raise HTTPException(status_code=403, detail="Request verification failed. Refresh and try again.")
    return user


async def record_usage(
    user: dict[str, Any] | None,
    feature: str,
    detail: str,
    item_count: int = 1,
) -> None:
    if user is None:
        return
    database = _database()
    await database.usage.insert_one(
        {
            "user_id": user["id"],
            "feature": feature,
            "detail": detail[:160],
            "item_count": max(1, item_count),
            "created_at": datetime.now(timezone.utc),
        }
    )


def _email_already_reserved_for_admin(email: str) -> bool:
    configured_admin = settings.ADMIN_EMAIL.strip()
    return bool(configured_admin and email == configured_admin.casefold())


@auth_router.post("/register", status_code=201)
async def register_account(payload: RegisterRequest, response: Response):
    database = _database()
    email = _normalize_email(payload.email)
    if _email_already_reserved_for_admin(email):
        raise HTTPException(status_code=409, detail="This email is reserved for the administrator.")

    user = {
        "id": secrets.token_hex(16),
        "full_name": payload.full_name.strip(),
        "email": email,
        "password_hash": _hash_password(payload.password),
        "role": "client",
        "active": True,
        "created_at": datetime.now(timezone.utc),
    }
    if len(user["full_name"]) < 2:
        raise HTTPException(status_code=422, detail="Enter your name.")

    try:
        await database.users.insert_one(user)
    except DuplicateKeyError as exc:
        raise HTTPException(status_code=409, detail="An account with this email already exists.") from exc

    raw_token, csrf_token = await _create_session(database, user)
    _set_session_cookie(response, raw_token)
    return {"user": _public_user(user), "csrf_token": csrf_token}


@auth_router.post("/login")
async def login(payload: LoginRequest, response: Response):
    database = _database()
    email = _normalize_email(payload.email)
    user = await database.users.find_one({"email": email})
    if user is None:
        _verify_password(payload.password, _DUMMY_PASSWORD_HASH)
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    if not _verify_password(payload.password, user.get("password_hash")):
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    if not user.get("active", False):
        raise HTTPException(status_code=403, detail="This account is suspended.")

    raw_token, csrf_token = await _create_session(database, user)
    _set_session_cookie(response, raw_token)
    return {"user": _public_user(user), "csrf_token": csrf_token}


@auth_router.get("/me")
async def current_account(
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
):
    session = request.state.auth_session
    return {"user": _public_user(user), "csrf_token": session["csrf_token"]}


@auth_router.post("/logout")
async def logout(request: Request, response: Response):
    raw_token = request.cookies.get(SESSION_COOKIE)
    if raw_token:
        database = get_database()
        if database is not None:
            await database.sessions.delete_one({"token_hash": _token_hash(raw_token)})
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        httponly=True,
        secure=settings.SESSION_COOKIE_SECURE or settings.APP_ENV.casefold() == "production",
        samesite="lax",
    )
    return {"status": "success"}
