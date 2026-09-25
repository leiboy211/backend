import datetime as dt
from collections import defaultdict

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_current_admin
from app.db import get_db
from app.models import User
from app.schemas import (
    LoginActivityDetailOut,
    LoginActivityTrendsOut,
    LoginStreakOut,
    LoginTrendPoint,
    PeakHourPoint,
    WeeklyActivePoint,
    RecentLoginOut,
    LoginLiveOut,
    LiveLoginPoint,
)
from app.models import LoginActivity
from app.services.login_activity_service import (
    daily_login_counts,
    peak_login_hours,
    user_login_streak,
    weekly_active_users,
    live_login_buckets,
)


router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/login-activity", response_model=LoginActivityDetailOut)
async def get_login_activity(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    daily = daily_login_counts(db, days=14)
    peak = peak_login_hours(db, days=30)
    weekly = weekly_active_users(db, weeks=8)
    streak = user_login_streak(db, current_user.id)
    recent_rows = (
        db.query(LoginActivity)
        .filter(LoginActivity.user_id == current_user.id)
        .order_by(LoginActivity.login_timestamp.desc())
        .limit(10)
        .all()
    )
    recent = [
        RecentLoginOut(
            login_timestamp=row.login_timestamp.isoformat(),
            device=row.device,
        )
        for row in recent_rows
        if row.login_timestamp
    ]
    return LoginActivityDetailOut(
        daily_counts=[LoginTrendPoint(**item) for item in daily],
        peak_hours=[PeakHourPoint(**item) for item in peak],
        weekly_active=[WeeklyActivePoint(**item) for item in weekly],
        streak=LoginStreakOut(current_streak=streak),
        recent_logins=recent,
    )


@router.get("/login-trends", response_model=LoginActivityTrendsOut)
async def get_login_trends(
    db: Session = Depends(get_db),
    current_admin=Depends(get_current_admin),
):
    daily = daily_login_counts(db, days=30)
    peak = peak_login_hours(db, days=30)
    weekly = weekly_active_users(db, weeks=104)
    per_user = []
    for user in db.query(User).filter(User.role == "student").all():
        per_user.append(
            LoginStreakOut(
                user_id=user.id,
                username=user.username,
                current_streak=user_login_streak(db, user.id),
            )
        )

    recent_cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)
    recent_rows = (
        db.query(LoginActivity, User)
        .join(User, User.id == LoginActivity.user_id)
        .filter(
            User.role == "student",
            LoginActivity.login_timestamp >= recent_cutoff,
        )
        .all()
    )
    program_users: dict[str, set[int]] = defaultdict(set)
    year_level_users: dict[str, set[int]] = defaultdict(set)
    for row, user in recent_rows:
        program = str(user.program or "").strip() or "Unspecified Program"
        year_level = str(user.year_level or "").strip() or "Unspecified Year Level"
        program_users[program].add(int(user.id))
        year_level_users[year_level].add(int(user.id))

    program_logins = [
        {"label": label, "count": len(user_ids)}
        for label, user_ids in sorted(program_users.items(), key=lambda item: (-len(item[1]), item[0].lower()))
    ]
    year_level_logins = [
        {"label": label, "count": len(user_ids)}
        for label, user_ids in sorted(year_level_users.items(), key=lambda item: (-len(item[1]), item[0].lower()))
    ]

    return LoginActivityTrendsOut(
        daily_counts=[LoginTrendPoint(**item) for item in daily],
        peak_hours=[PeakHourPoint(**item) for item in peak],
        weekly_active=[WeeklyActivePoint(**item) for item in weekly],
        streaks=per_user,
        program_logins=program_logins,
        year_level_logins=year_level_logins,
    )


@router.get("/login-live", response_model=LoginLiveOut)
async def get_login_live(
    db: Session = Depends(get_db),
    current_admin=Depends(get_current_admin),
):
    hours = 24
    bucket_minutes = 10
    points = live_login_buckets(db, hours=hours, bucket_minutes=bucket_minutes, anchor_hour=0)
    return LoginLiveOut(
        window_hours=hours,
        bucket_minutes=bucket_minutes,
        points=[LiveLoginPoint(**item) for item in points],
    )
