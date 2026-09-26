import datetime as dt
from collections import defaultdict
try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.models import LoginActivity, User


try:
    MANILA_TZ = ZoneInfo("Asia/Manila") if ZoneInfo else dt.timezone(dt.timedelta(hours=8))
except Exception:
    MANILA_TZ = dt.timezone(dt.timedelta(hours=8))


def record_login(
    db: Session,
    user: User,
    ip_address: str | None,
    device: str | None,
) -> None:
    now = dt.datetime.now(tz=MANILA_TZ)
    login_date = now.date().isoformat()
    login_hour = now.hour
    activity = LoginActivity(
        user_id=user.id,
        login_timestamp=now,
        login_date=login_date,
        login_hour=login_hour,
        ip_address=ip_address,
        device=device,
    )
    db.add(activity)
    try:
        db.commit()
    except IntegrityError:
        # A stale PostgreSQL sequence can collide once after a data import.
        # Roll back and retry so analytics cannot block authentication.
        db.rollback()
        db.add(
            LoginActivity(
                user_id=user.id,
                login_timestamp=now,
                login_date=login_date,
                login_hour=login_hour,
                ip_address=ip_address,
                device=device,
            )
        )
        db.commit()


def daily_login_counts(db: Session, days: int = 14) -> list[dict]:
    today = dt.datetime.now(tz=MANILA_TZ).date()
    dates = [today - dt.timedelta(days=offset) for offset in range(days - 1, -1, -1)]
    date_map = {date.isoformat(): 0 for date in dates}
    since = dt.datetime.combine(dates[0], dt.time.min, tzinfo=MANILA_TZ)
    rows = (
        db.query(LoginActivity)
        .filter(LoginActivity.login_timestamp >= since)
        .all()
    )
    for row in rows:
        if row.login_date in date_map:
            date_map[row.login_date] += 1
    return [{"date": key, "count": value} for key, value in date_map.items()]


def peak_login_hours(db: Session, days: int = 30) -> list[dict]:
    today = dt.datetime.now(tz=MANILA_TZ).date()
    since = dt.datetime.combine(today - dt.timedelta(days=days - 1), dt.time.min, tzinfo=MANILA_TZ)
    hour_counts = defaultdict(int)
    rows = (
        db.query(LoginActivity)
        .filter(LoginActivity.login_timestamp >= since)
        .all()
    )
    for row in rows:
        hour_counts[int(row.login_hour)] += 1
    return [{"hour": hour, "count": hour_counts.get(hour, 0)} for hour in range(24)]


def weekly_active_users(db: Session, weeks: int = 8) -> list[dict]:
    today = dt.datetime.now(tz=MANILA_TZ).date()
    start = today - dt.timedelta(weeks=weeks - 1)
    start_dt = dt.datetime.combine(start, dt.time.min, tzinfo=MANILA_TZ)
    rows = (
        db.query(LoginActivity)
        .filter(LoginActivity.login_timestamp >= start_dt)
        .all()
    )
    weekly_users: dict[str, set[int]] = defaultdict(set)
    for row in rows:
        login_dt = row.login_timestamp
        if login_dt.tzinfo is None:
            login_dt = login_dt.replace(tzinfo=MANILA_TZ)
        week_start = login_dt.date() - dt.timedelta(days=login_dt.weekday())
        key = week_start.isoformat()
        weekly_users[key].add(row.user_id)
    buckets = []
    for offset in range(weeks):
        week_start = (today - dt.timedelta(days=today.weekday())) - dt.timedelta(weeks=weeks - 1 - offset)
        key = week_start.isoformat()
        buckets.append({"week_start": key, "active_users": len(weekly_users.get(key, set()))})
    return buckets


def user_login_streak(db: Session, user_id: int) -> int:
    rows = (
        db.query(LoginActivity)
        .filter(LoginActivity.user_id == user_id)
        .order_by(LoginActivity.login_date.desc())
        .all()
    )
    if not rows:
        return 0
    unique_dates = sorted({row.login_date for row in rows}, reverse=True)
    streak = 0
    today = dt.datetime.now(tz=MANILA_TZ).date()
    cursor = today
    for date_str in unique_dates:
        if date_str == cursor.isoformat():
            streak += 1
            cursor -= dt.timedelta(days=1)
        elif date_str < cursor.isoformat():
            break
    return streak


def live_login_buckets(
    db: Session, hours: int = 12, bucket_minutes: int = 10, anchor_hour: int = 23
) -> list[dict]:
    now = dt.datetime.now(tz=MANILA_TZ)
    anchor = now.replace(hour=anchor_hour, minute=0, second=0, microsecond=0)
    if now < anchor:
        anchor -= dt.timedelta(days=1)
    start = anchor
    bucket_count = int((hours * 60) / bucket_minutes)
    buckets = [start + dt.timedelta(minutes=bucket_minutes * idx) for idx in range(bucket_count)]
    label_map = {bucket.strftime("%H:%M"): set() for bucket in buckets}
    since = buckets[0]
    rows = (
        db.query(LoginActivity)
        .filter(LoginActivity.login_timestamp >= since)
        .all()
    )
    for row in rows:
        login_dt = row.login_timestamp
        if login_dt.tzinfo is None:
            login_dt = login_dt.replace(tzinfo=MANILA_TZ)
        offset = int((login_dt - since).total_seconds() // (bucket_minutes * 60))
        if offset < 0 or offset >= bucket_count:
            continue
        bucket_dt = since + dt.timedelta(minutes=bucket_minutes * offset)
        label = bucket_dt.strftime("%H:%M")
        if label in label_map:
            label_map[label].add(row.user_id)
    return [{"time": label, "count": len(users)} for label, users in label_map.items()]
