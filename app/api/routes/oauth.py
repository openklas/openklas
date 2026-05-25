"""
OAuth 2.0 endpoints for Claude / AI assistant connector integration.

Flow:
  1. Claude hits /.well-known/oauth-authorization-server → discovers endpoints
  2. Claude registers a client: POST /oauth/register
  3. Claude redirects user to GET /oauth/authorize (HTML login form)
  4. User submits KLAS credentials → POST /oauth/authorize
     - Authenticates against KLAS
     - Encrypts & stores credentials in DB for silent re-auth
     - Issues auth code, redirects back to Claude
  5. Claude exchanges code: POST /oauth/token → gets long-lived access_token
  6. Claude uses access_token as Bearer for all MCP tool calls
"""
import hashlib
import base64
import secrets
import time
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DbSession
from app.core.encryption import decrypt, encrypt
from app.core.security import create_session
from app.db.session import get_db
from app.models.oauth import OAuthToken
from app.models.user import User
from app.services.klas_service import KLASService

router = APIRouter()

# Short-lived authorization codes: code → {access_token, code_challenge, expires_at}
_auth_codes: dict[str, dict] = {}

_LOGIN_HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>KLAS 로그인</title>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f0f2f5;display:flex;align-items:center;justify-content:center;min-height:100vh}}
    .card{{background:#fff;border-radius:16px;padding:44px 40px;width:100%;max-width:420px;box-shadow:0 8px 32px rgba(0,0,0,.10)}}
    .logo{{text-align:center;font-size:22px;font-weight:700;color:#1a1a2e;margin-bottom:4px}}
    .sub{{text-align:center;color:#888;font-size:13px;margin-bottom:28px}}
    label{{display:block;font-size:13px;font-weight:500;color:#555;margin-bottom:5px}}
    .field{{margin-bottom:16px}}
    input[type=text],input[type=password]{{width:100%;padding:11px 14px;border:1.5px solid #e2e8f0;border-radius:8px;font-size:14px;outline:none;transition:border-color .2s}}
    input:focus{{border-color:#6366f1}}
    .error{{background:#fef2f2;border:1px solid #fca5a5;color:#dc2626;padding:10px 14px;border-radius:8px;font-size:13px;margin-bottom:16px}}
    button{{width:100%;padding:12px;background:#6366f1;color:#fff;border:none;border-radius:8px;font-size:15px;font-weight:600;cursor:pointer;margin-top:4px;transition:background .2s}}
    button:hover{{background:#4f46e5}}
    button:disabled{{background:#a5b4fc;cursor:not-allowed}}
    .notice{{margin-top:20px;font-size:12px;color:#aaa;text-align:center;line-height:1.7}}
  </style>
</head>
<body>
  <div class="card">
    <div class="logo">OpenKLAS</div>
    <div class="sub">AI 어시스턴트에 KLAS를 연결합니다</div>
    {error_html}
    <form method="POST" action="/oauth/authorize" onsubmit="this.querySelector('button').disabled=true">
      <input type="hidden" name="client_id" value="{client_id}">
      <input type="hidden" name="redirect_uri" value="{redirect_uri}">
      <input type="hidden" name="state" value="{state}">
      <input type="hidden" name="code_challenge" value="{code_challenge}">
      <input type="hidden" name="code_challenge_method" value="{code_challenge_method}">
      <div class="field">
        <label>학번 / Student ID</label>
        <input type="text" name="student_id" placeholder="20XXXXXXXXXX" required autofocus autocomplete="username">
      </div>
      <div class="field">
        <label>비밀번호 / Password</label>
        <input type="password" name="password" placeholder="••••••••" required autocomplete="current-password">
      </div>
      <button type="submit">로그인 / Login</button>
    </form>
    <p class="notice">
      자격증명은 AES-256으로 암호화되어 저장됩니다.<br>
      Credentials are stored encrypted for automatic session refresh.<br>
      Your data is never shared with third parties.
    </p>
  </div>
</body>
</html>"""


def _render_login(
    client_id: str,
    redirect_uri: str,
    state: str,
    code_challenge: str = "",
    code_challenge_method: str = "",
    error: str = "",
) -> str:
    error_html = f'<div class="error">{error}</div>' if error else ""
    return _LOGIN_HTML.format(
        client_id=client_id,
        redirect_uri=redirect_uri,
        state=state,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        error_html=error_html,
    )


def _verify_pkce(code_verifier: str, code_challenge: str) -> bool:
    digest = hashlib.sha256(code_verifier.encode()).digest()
    computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return computed == code_challenge


# ── OAuth discovery ───────────────────────────────────────────────────────────

@router.get("/.well-known/oauth-authorization-server", operation_id="oauth_metadata")
async def oauth_metadata(request: Request):
    base = str(request.base_url).rstrip("/")
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/oauth/authorize",
        "token_endpoint": f"{base}/oauth/token",
        "registration_endpoint": f"{base}/oauth/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "token_endpoint_auth_methods_supported": ["client_secret_post", "none"],
        "scopes_supported": ["klas"],
        "code_challenge_methods_supported": ["S256"],
    }


# ── Dynamic client registration (RFC 7591) ───────────────────────────────────

@router.post("/oauth/register")
async def register_client(request: Request):
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    return JSONResponse(
        {
            "client_id": secrets.token_urlsafe(16),
            "client_secret": secrets.token_urlsafe(32),
            "redirect_uris": body.get("redirect_uris", []),
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "client_secret_post",
        },
        status_code=201,
    )


# ── Authorization endpoint ────────────────────────────────────────────────────

@router.get("/oauth/authorize", response_class=HTMLResponse)
async def authorize_form(
    client_id: str,
    redirect_uri: str,
    state: str,
    response_type: str = "code",
    code_challenge: Optional[str] = None,
    code_challenge_method: Optional[str] = None,
    scope: Optional[str] = None,
):
    return HTMLResponse(_render_login(
        client_id=client_id,
        redirect_uri=redirect_uri,
        state=state,
        code_challenge=code_challenge or "",
        code_challenge_method=code_challenge_method or "",
    ))


@router.post("/oauth/authorize")
async def authorize_submit(
    request: Request,
    student_id: str = Form(...),
    password: str = Form(...),
    client_id: str = Form(...),
    redirect_uri: str = Form(...),
    state: str = Form(...),
    code_challenge: str = Form(""),
    code_challenge_method: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    # Authenticate against KLAS
    klas = KLASService()
    if not klas.login(student_id, password):
        return HTMLResponse(
            _render_login(
                client_id=client_id,
                redirect_uri=redirect_uri,
                state=state,
                code_challenge=code_challenge,
                code_challenge_method=code_challenge_method,
                error="학번 또는 비밀번호가 올바르지 않습니다. / Invalid student ID or password.",
            ),
            status_code=401,
        )

    # Store encrypted credentials + create KLAS session
    enc_id = encrypt(student_id)
    enc_pw = encrypt(password)
    access_token = secrets.token_urlsafe(32)
    klas_session_token = create_session(student_id, klas, password)
    klas_expires_at = datetime.now() + timedelta(minutes=55)

    # Upsert: one OAuth token per student
    result = await db.execute(
        select(OAuthToken).where(OAuthToken.student_id == student_id)
    )
    record = result.scalar_one_or_none()
    now = datetime.now()

    if record:
        record.access_token = access_token
        record.encrypted_student_id = enc_id
        record.encrypted_password = enc_pw
        record.klas_session_token = klas_session_token
        record.klas_session_expires_at = klas_expires_at
        record.last_used_at = now
    else:
        record = OAuthToken(
            access_token=access_token,
            student_id=student_id,
            encrypted_student_id=enc_id,
            encrypted_password=enc_pw,
            klas_session_token=klas_session_token,
            klas_session_expires_at=klas_expires_at,
            last_used_at=now,
        )
        db.add(record)

    await db.commit()

    # Ensure user exists in users table (profile fetch best-effort)
    result2 = await db.execute(select(User).where(User.student_id == student_id))
    user = result2.scalar_one_or_none()
    if not user:
        try:
            profile = klas.get_profile()
        except Exception:
            profile = {"student_id": student_id}
        user = User(
            student_id=profile.get("student_id") or student_id,
            name=profile.get("name"),
            major=profile.get("major"),
            role="worker",
            status="pending",
        )
        db.add(user)
        await db.commit()

    # Issue short-lived auth code
    code = secrets.token_urlsafe(32)
    _auth_codes[code] = {
        "access_token": access_token,
        "code_challenge": code_challenge,
        "code_challenge_method": code_challenge_method,
        "expires_at": time.time() + 300,
    }

    return RedirectResponse(
        f"{redirect_uri}?code={code}&state={state}",
        status_code=302,
    )


# ── Token endpoint ────────────────────────────────────────────────────────────

@router.post("/oauth/token")
async def token_exchange(request: Request):
    content_type = request.headers.get("content-type", "")
    if "application/x-www-form-urlencoded" in content_type:
        form = await request.form()
        data = dict(form)
    else:
        try:
            data = await request.json()
        except Exception:
            data = {}

    grant_type = data.get("grant_type")
    if grant_type != "authorization_code":
        raise HTTPException(400, detail={"error": "unsupported_grant_type"})

    code = data.get("code", "")
    code_data = _auth_codes.pop(code, None)
    if not code_data or time.time() > code_data["expires_at"]:
        raise HTTPException(400, detail={"error": "invalid_grant"})

    # Validate PKCE if challenge was provided
    code_verifier = data.get("code_verifier", "")
    stored_challenge = code_data.get("code_challenge", "")
    if stored_challenge and code_verifier:
        if not _verify_pkce(code_verifier, stored_challenge):
            raise HTTPException(400, detail={"error": "invalid_grant"})

    return {
        "access_token": code_data["access_token"],
        "token_type": "bearer",
        "expires_in": 86400 * 365,  # 1 year; KLAS sessions are refreshed behind the scenes
    }
