import datetime as dt
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.db import get_db
from app.models import ActivityLog, EngagementCommit, LearningProgress, User, XpHistory
from app.schemas import EngagementAnalyticsOut, ActivityTimelineOut
from app.services.engagement_service import refresh_engagement, compute_engagement_score, calculate_learning_progress


router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/engagement", response_model=EngagementAnalyticsOut)
async def get_engagement_analytics(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        weekly_commits_data, new_repo_counts, xp_growth_data = refresh_engagement(db, current_user)
    except Exception:
        weekly_commits_data, new_repo_counts, xp_growth_data = ([], {}, [])
    weekly_commits = (
        db.query(EngagementCommit)
        .filter(EngagementCommit.user_id == current_user.id)
        .order_by(EngagementCommit.week_start.asc())
        .all()
    )
    xp_growth = (
        db.query(XpHistory)
        .filter(XpHistory.user_id == current_user.id)
        .order_by(XpHistory.week_start.asc())
        .all()
    )
    progress_rows = (
        db.query(LearningProgress)
        .filter(LearningProgress.user_id == current_user.id)
        .all()
    )
    learning_progress = calculate_learning_progress(progress_rows)
    score = compute_engagement_score(
        weekly_commits_data,
        len(learning_progress),
        new_repo_counts,
        xp_growth_data,
    )
    return {
        "weekly_commits": [
            {"week_start": row.week_start.isoformat(), "commit_count": row.commit_count}
            for row in weekly_commits
        ],
        "xp_growth": [
            {"week_start": row.week_start.isoformat(), "xp_gained": row.xp_gained}
            for row in xp_growth
        ],
        "learning_progress": learning_progress,
        "engagement_score": score,
    }


@router.get("/activity-timeline", response_model=list[ActivityTimelineOut])
async def get_activity_timeline(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    logs = (
        db.query(ActivityLog)
        .filter(ActivityLog.user_id == current_user.id)
        .order_by(ActivityLog.created_at.desc())
        .limit(50)
        .all()
    )
    timeline = []
    label_map = {
        "login": "Logged in",
        "logout": "Logged out",
        "recompute": "Recomputed insights",
        "profile_update": "Updated profile",
        "learning_path_view": "Viewed learning path",
        "project_learning_path_view": "Viewed project learning path",
        "heartbeat": "Active session",
    }
    for log in logs:
        created_at = log.created_at.isoformat() if log.created_at else dt.datetime.utcnow().isoformat()
        timeline.append({"date": created_at, "event": label_map.get(log.event, log.event)})
    return timeline
