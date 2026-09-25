from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from urllib.parse import urlencode

from app.core.config import settings
from app.core.security import create_access_token, decode_access_token
from app.core.passwords import hash_password, verify_password
from app.core.dependencies import get_current_user
from app.db import ensure_schema_initialized, get_db
from app.models import Badge, CareerSuggestion, PracticeDimension, Repo, User, PortfolioSettings, AdminAccount, ActivityLog
from app.models import CertificateRecord, DailyQuestClaim, WeeklyChallengeClaim
from app.schemas import AdminLoginIn, AdminLoginOut
from app.services.github import (
    exchange_code_for_token,
    fetch_github_user,
    fetch_commit_streak_days,
    fetch_repos,
    dedupe_repo_summaries,
    summarize_repo,
)
from app.services.gamification import compute_xp_and_badges
from app.services.badge_sync import upsert_badges
from app.services.inference import infer_practice_and_careers
from app.services.login_activity_service import record_login

import logging


router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)
_REGISTRATION_FIELDS = ("display_name", "student_id", "program", "year_level")


def _build_badge_context(db: Session, user: User) -> dict:
    try:
        streak_days = fetch_commit_streak_days(user.username, token=user.github_token)
    except Exception:
        streak_days = 0
    practice_rows = db.query(PracticeDimension).filter(PracticeDimension.user_id == user.id).all()
    practice_dimensions = [
        {"label": item.label, "confidence": item.confidence, "evidence": item.evidence}
        for item in practice_rows
    ]
    return {
        "streak_days": int(streak_days or 0),
        "practice_dimensions": practice_dimensions,
        "certificate_verified_count": (
            db.query(CertificateRecord)
            .filter(CertificateRecord.user_id == user.id, CertificateRecord.status == "verified")
            .count()
        ),
        "certificate_total_count": (
            db.query(CertificateRecord)
            .filter(CertificateRecord.user_id == user.id)
            .count()
        ),
        "daily_quest_claim_count": (
            db.query(DailyQuestClaim)
            .filter(DailyQuestClaim.user_id == user.id)
            .count()
        ),
        "weekly_challenge_claim_count": (
            db.query(WeeklyChallengeClaim)
            .filter(WeeklyChallengeClaim.user_id == user.id)
            .count()
        ),
        "has_portfolio_settings": (
            db.query(PortfolioSettings).filter(PortfolioSettings.user_id == user.id).one_or_none() is not None
        ),
    }


def _registration_complete(user: User) -> bool:
    return all(str(getattr(user, field, "") or "").strip() for field in _REGISTRATION_FIELDS)


def _frontend_auth_error_redirect(error_code: str) -> RedirectResponse:
    redirect_url = f"{settings.frontend_url}/?{urlencode({'auth_error': error_code})}"
    return RedirectResponse(url=redirect_url, status_code=302)


@router.get("/github/login")
async def github_login():
    url = "https://github.com/login/oauth/authorize?" + urlencode(
        {
            "client_id": settings.github_client_id,
            "redirect_uri": settings.github_redirect_uri,
            "scope": "read:user repo",
        }
    )
    return RedirectResponse(url=url, status_code=302)


@router.get("/github/callback")
async def github_callback(
    request: Request,
    code: str | None = Query(default=None),
    error: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    if error or not code:
        return _frontend_auth_error_redirect("github_authorization_cancelled")

    ensure_schema_initialized(force=True)
    try:
        token = exchange_code_for_token(
            settings.github_client_id,
            settings.github_client_secret,
            code,
            settings.github_redirect_uri,
        )
    except Exception:
        logger.exception("GitHub OAuth token exchange failed")
        return _frontend_auth_error_redirect("github_oauth_failed")
    try:
        gh_user = fetch_github_user(token)
    except Exception:
        logger.exception("GitHub profile fetch failed")
        return _frontend_auth_error_redirect("github_profile_fetch_failed")

    github_id = str(gh_user["id"])
    username = gh_user["login"]
    avatar_url = gh_user.get("avatar_url") or ""
    display_name = gh_user.get("name")
    bio = gh_user.get("bio")

    user = db.query(User).filter(User.github_id == github_id).one_or_none()
    is_new = False
    admin_usernames = {
        item.strip().lower()
        for item in (settings.admin_usernames or "").split(",")
        if item.strip()
    }
    role = "admin" if username.lower() in admin_usernames else "student"
    if not user:
        user = User(
            github_id=github_id,
            username=username,
            avatar_url=avatar_url,
            display_name=display_name,
            bio=bio,
            github_token=token,
            role=role,
        )
        db.add(user)
        db.flush()
        db.add(PortfolioSettings(user_id=user.id))
        is_new = True
    else:
        user.github_token = token
        if role == "admin":
            user.role = role
        elif not str(user.role or "").strip():
            user.role = "student"
    user.last_seen = func.now()

    try:
        repos_raw = fetch_repos(token)
    except Exception:
        repos_raw = []
    summaries = []
    # Keep OAuth callback fast. Heavy per-repo GitHub calls make login feel frozen,
    # especially for students with many repositories. The repo's own metadata is
    # enough for initial personalization; deeper stats can be recomputed later.
    for repo in repos_raw[:30]:
        full_name = repo.get("full_name", "")
        language = repo.get("language")
        languages = [language] if language else []
        language_bytes = {}
        commit_count = 0
        summaries.append(
            summarize_repo(
                repo,
                languages,
                commit_count=commit_count,
                language_bytes=language_bytes,
            )
        )

    summaries = dedupe_repo_summaries(summaries)

    db.query(Repo).filter(Repo.user_id == user.id).delete(synchronize_session=False)
    for repo in summaries:
        db.add(Repo(user_id=user.id, **repo))

    inference = infer_practice_and_careers(summaries)
    db.query(PracticeDimension).filter(PracticeDimension.user_id == user.id).delete()
    for item in inference.get("practice_dimensions", []):
        db.add(
            PracticeDimension(
                user_id=user.id,
                label=item["label"],
                confidence=item["confidence"],
                evidence=item.get("evidence", []),
            )
        )
    db.query(CareerSuggestion).filter(CareerSuggestion.user_id == user.id).delete()
    for item in inference.get("career_suggestions", []):
        db.add(
            CareerSuggestion(
                user_id=user.id,
                title=item["title"],
                confidence=item["confidence"],
                reasoning=item["reasoning"],
            )
        )

    gamification = compute_xp_and_badges(summaries, context=_build_badge_context(db, user))
    upsert_badges(db, user.id, gamification.badges, preserve_achieved=False, clear_claimed_when_unachieved=True)

    db.add(ActivityLog(user_id=user.id, event="login"))
    db.commit()
    ip_address = request.client.host if request and request.client else None
    device = request.headers.get("user-agent") if request else None
    try:
        record_login(db, user, ip_address, device)
    except Exception as exc:
        # Login should still succeed even if the analytics write fails.
        logger.warning("Login activity record failed for user %s: %s", user.username, str(exc)[:240])

    jwt_token = create_access_token(str(user.id), settings.jwt_secret, settings.jwt_issuer, role=user.role)
    if is_new or not _registration_complete(user):
        path = "/register"
    else:
        path = "/dashboard"

    params = {
        "token": jwt_token,
        "username": user.username,
        "avatar": user.avatar_url or "",
    }
    redirect_url = f"{settings.frontend_url}{path}?{urlencode(params)}"

    return RedirectResponse(url=redirect_url, status_code=302)


@router.post("/admin/login", response_model=AdminLoginOut)
async def admin_login(payload: AdminLoginIn, db: Session = Depends(get_db)):
    if not payload.username or not payload.password:
        raise HTTPException(status_code=400, detail="Missing credentials")

    admin = db.query(AdminAccount).filter(AdminAccount.username == payload.username).one_or_none()
    if not admin:
        if not settings.admin_login_username or not settings.admin_login_password:
            raise HTTPException(status_code=401, detail="Admin login not configured")
        if payload.username != settings.admin_login_username:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        hashed, salt = hash_password(settings.admin_login_password)
        admin = AdminAccount(
            username=settings.admin_login_username,
            password_hash=hashed,
            password_salt=salt,
            role="admin",
        )
        db.add(admin)
        db.commit()
        db.refresh(admin)

    if (admin.role or "admin") != "admin":
        raise HTTPException(status_code=403, detail="Use faculty login for this account")

    if not verify_password(payload.password, admin.password_hash, admin.password_salt):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token(
        f"admin:{admin.id}",
        settings.jwt_secret,
        settings.jwt_issuer,
        role="admin",
    )
    return AdminLoginOut(username=admin.username, token=token, role="admin")


@router.post("/faculty/login", response_model=AdminLoginOut)
async def faculty_login(payload: AdminLoginIn, db: Session = Depends(get_db)):
    if not payload.username or not payload.password:
        raise HTTPException(status_code=400, detail="Missing credentials")

    faculty = db.query(AdminAccount).filter(AdminAccount.username == payload.username).one_or_none()
    if not faculty:
        if not settings.faculty_login_username or not settings.faculty_login_password:
            raise HTTPException(status_code=401, detail="Faculty login not configured")
        if payload.username != settings.faculty_login_username:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        hashed, salt = hash_password(settings.faculty_login_password)
        faculty = AdminAccount(
            username=settings.faculty_login_username,
            password_hash=hashed,
            password_salt=salt,
            role="faculty",
        )
        db.add(faculty)
        db.commit()
        db.refresh(faculty)

    if (faculty.role or "admin") != "faculty":
        raise HTTPException(status_code=403, detail="Use admin login for this account")

    if not verify_password(payload.password, faculty.password_hash, faculty.password_salt):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token(
        f"admin:{faculty.id}",
        settings.jwt_secret,
        settings.jwt_issuer,
        role="faculty",
    )
    return AdminLoginOut(username=faculty.username, token=token, role="faculty")
