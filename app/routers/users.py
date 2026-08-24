from fastapi import APIRouter, Depends, HTTPException, Query, Header, UploadFile, File
import os
import time
import shutil
import hashlib
import datetime as dt
import re
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy import func, or_

from app.core.config import settings
from app.core.dependencies import get_current_user
from app.core.security import decode_access_token
from app.db import get_db
from app.models import (
    Badge,
    CareerSuggestion,
    PracticeDimension,
    Repo,
    User,
    PortfolioSettings,
    ActivityLog,
    LearningProgress,
    CertificateRecord,
    FccModuleProgress,
    ProjectValidation,
    DailyQuestClaim,
    WeeklyChallengeClaim,
    RecommendationAction,
    StudentGoal,
)
from app.schemas import (
    PortfolioResponse,
    PortfolioSettingsIn,
    UserResponse,
    RegistrationIn,
    LeaderboardBadgeOut,
    LeaderboardEntryOut,
    LearningPathResponse,
    ProjectLearningPathResponse,
    CertificateSuggestionListOut,
    CurriculumMapOut,
    RuleRecommendationListOut,
    WeeklyDigestOut,
    CertificateSubmitIn,
    AutoStageCertificateIn,
    CertificateOut,
    CertificateCommentIn,
    CertificateStudentCommentDeleteIn,
    CertificateProgressDeleteIn,
    CertificateRewardClaimIn,
    FccModuleProgressIn,
    FccModuleProgressListOut,
    FccModuleProgressOut,
    ProjectStageStatusIn,
    ProjectStageStatusOut,
    ProjectStageProgressDeleteIn,
    ProjectStageFeedbackReplyIn,
    ProjectStageFeedbackReplyDeleteIn,
    ProjectStageProofDeleteIn,
    ProjectStageProgressUpdateIn,
    ProjectStageProgressUpdateOut,
    ProjectLearningPathClaimIn,
    ProjectLearningPathClaimOut,
    ProjectStageResetIn,
    ProjectStageResetOut,
    StudentGoalIn,
    StudentGoalOut,
    StudentGoalUpdateIn,
    ProjectValidationOut,
    LearningAccountsIn,
    LearningAccountsOut,
    LearningAccountStatsOut,
    AutoSyncResultOut,
    QuestListOut,
    QuestClaimIn,
    ChallengeListOut,
    ChallengeClaimIn,
    RecommendationActionIn,
)


from app.services.github import (
    fetch_commit_streak_days,
    fetch_repos,
    fetch_repo_language_bytes,
    fetch_repo_languages,
    fetch_public_repo_language_bytes,
    fetch_public_repo_languages,
    fetch_public_repos,
    fetch_repo_commit_count,
    summarize_repo,
)
from app.services.inference import infer_practice_and_careers, infer_learning_path, infer_project_learning_paths
from app.services.gamification import (
    badge_reward_xp,
    badge_visuals,
    compute_xp_and_badges,
    humanize_badge_criteria,
    level_from_xp,
    next_level_xp_for_total,
)
from app.services import llm_refiner
from app.services.learning_path import (
    build_signal_set,
    annotate_steps_with_status,
    build_competency_levels,
    identify_skill_gaps,
    generate_personalized_learning_path,
)
from app.services.engagement_service import refresh_engagement, compute_engagement_score, calculate_learning_progress
from app.models import EngagementCommit, XpHistory
from app.services.engagement_service import week_start_for_date
from app.services.certificate_sync import get_freecodecamp_stats, sync_freecodecamp_certificates
from app.services.badge_sync import upsert_badges


router = APIRouter(prefix="/api", tags=["users"])

MAX_PROJECT_PATH_LEVEL = 3
BADGE_REPAIR_EVENT = "badge_claim_repair_20260524"

ADOPTED_RECOMMENDATION_ACTIONS = {"clicked", "accepted", "completed", "started"}

FCC_CERT_MODULE_MAP = {
    "responsive-web-design": ("fcc-rwd", "Responsive Web Design Certification"),
    "javascript-algorithms-and-data-structures-v8": ("fcc-js", "JavaScript Algorithms and Data Structures"),
    "front-end-development-libraries": ("fcc-frontend", "Front End Development Libraries"),
    "back-end-development-and-apis": ("fcc-backend", "Back End Development and APIs"),
    "data-analysis-with-python-v7": ("fcc-data-analysis", "Data Analysis with Python"),
    "machine-learning-with-python-v7": ("fcc-ml", "Machine Learning with Python"),
    "quality-assurance-v7": ("fcc-qa", "Quality Assurance"),
    "information-security": ("fcc-info-sec", "Information Security"),
}

CURRICULUM_SUBJECTS = [
    {
        "code": "CS101",
        "title": "Introduction to Computing",
        "program": "BSCS/BSIT",
        "year_level": 1,
        "focus_dimension_key": "frontend_engineering",
        "recommended_module": "Responsive Web Design",
    },
    {
        "code": "CS102",
        "title": "Computer Programming 1",
        "program": "BSCS/BSIT",
        "year_level": 1,
        "focus_dimension_key": "backend_systems_engineering",
        "recommended_module": "Python Basics",
    },
    {
        "code": "CS203",
        "title": "Data Structures and Algorithms",
        "program": "BSCS",
        "year_level": 2,
        "focus_dimension_key": "backend_systems_engineering",
        "recommended_module": "Algorithm Design",
    },
    {
        "code": "IT204",
        "title": "Database Management Systems",
        "program": "BSIT",
        "year_level": 2,
        "focus_dimension_key": "data_science_intelligence",
        "recommended_module": "Relational Data and SQL",
    },
    {
        "code": "CS305",
        "title": "Software Engineering",
        "program": "BSCS/BSIT",
        "year_level": 3,
        "focus_dimension_key": "backend_systems_engineering",
        "recommended_module": "API Testing and Design",
    },
    {
        "code": "IT306",
        "title": "Network and Security",
        "program": "BSIT",
        "year_level": 3,
        "focus_dimension_key": "systems_devops_engineering",
        "recommended_module": "Cybersecurity Fundamentals",
    },
    {
        "code": "CS307",
        "title": "Intelligent Systems",
        "program": "BSCS",
        "year_level": 3,
        "focus_dimension_key": "data_science_intelligence",
        "recommended_module": "Machine Learning Foundations",
    },
    {
        "code": "CSIT401",
        "title": "Capstone Project",
        "program": "BSCS/BSIT",
        "year_level": 4,
        "focus_dimension_key": "systems_devops_engineering",
        "recommended_module": "DevOps and Deployment",
    },
]

RULE_MODULES = {
    "frontend_engineering": [
        {
            "module_title": "freeCodeCamp: Responsive Web Design Certification",
            "module_url": "https://www.freecodecamp.org/learn/2022/responsive-web-design/",
            "certificate_hint": "Free certificate on completion.",
        },
        {
            "module_title": "MDN Learn: HTML, CSS, and JavaScript",
            "module_url": "https://developer.mozilla.org/en-US/docs/Learn",
            "certificate_hint": "High-quality web docs and guided modules.",
        },
        {
            "module_title": "The Odin Project: Full Stack JavaScript",
            "module_url": "https://www.theodinproject.com/paths/full-stack-javascript",
            "certificate_hint": "Project-based full-stack path.",
            "certificate_hint": "Microsoft learning path with applied labs.",
        },
        {
            "module_title": "IBM SkillsBuild: Backend Development",
            "module_url": "https://skillsbuild.org/",
            "certificate_hint": "Industry learning content with badges/certificates.",
        },
    ],
    "data_science_intelligence": [
        {
            "module_title": "freeCodeCamp: Data Analysis with Python",
            "module_url": "https://www.freecodecamp.org/learn/data-analysis-with-python/",
            "certificate_hint": "Free certificate on completion.",
        },
        {
            "module_title": "Kaggle Learn: Intro to Machine Learning",
            "module_url": "https://www.kaggle.com/learn/intro-to-machine-learning",
            "certificate_hint": "Short practical micro-courses with hands-on notebooks.",
        },
        {
            "module_title": "Google Cloud Skills Boost: Data and ML fundamentals",
            "module_url": "https://www.cloudskillsboost.google/",
            "certificate_hint": "Cloud-based data/ML labs and skill badges.",
        },
    ],
    "systems_devops_engineering": [
        {
            "module_title": "freeCodeCamp: Information Security",
            "module_url": "https://www.freecodecamp.org/learn/information-security/",
            "certificate_hint": "Free certificate on completion.",
        },
        {
            "module_title": "AWS Skill Builder: Cloud Practitioner Essentials",
            "module_url": "https://explore.skillbuilder.aws/learn",
            "certificate_hint": "Cloud and DevOps baseline from AWS.",
        },
        {
            "module_title": "Microsoft Learn: DevOps Engineer learning path",
            "module_url": "https://learn.microsoft.com/en-us/training/career-paths/devops-engineer",
            "certificate_hint": "Structured DevOps preparation path.",
        },
    ],
}


def _pick_rule_module(dimension_key: str, username: str, order_index: int = 0) -> dict | None:
    options = RULE_MODULES.get(dimension_key) or []
    if not options:
        return None
    # Deterministic spread so users get varied providers, not only one platform.
    seed = sum(ord(ch) for ch in f"{username}:{dimension_key}") + int(order_index or 0)
    return options[seed % len(options)]

DAILY_QUESTS = [
    {
        "key": "daily_login",
        "title": "Daily Login",
        "description": "Open your dashboard and stay active today.",
        "reward_xp": 20,
    },
    {
        "key": "daily_learning_view",
        "title": "Learning Path Check",
        "description": "View your learning paths today.",
        "reward_xp": 30,
    },
    {
        "key": "daily_recompute",
        "title": "Insight Refresh",
        "description": "Run a recompute today.",
        "reward_xp": 40,
    },
]

WEEKLY_CHALLENGES = [
    {
        "key": "weekly_commit_10",
        "title": "Commit Sprint",
        "description": "Reach 10 commits this week.",
        "reward_xp": 150,
    },
    {
        "key": "weekly_learning_2",
        "title": "Learning Momentum",
        "description": "Complete 2 learning steps this week.",
        "reward_xp": 120,
    },
    {
        "key": "weekly_cert_1",
        "title": "Certified This Week",
        "description": "Get at least 1 verified certificate this week.",
        "reward_xp": 180,
    },
]


def _add_bonus_xp(db: Session, user: User, reward_xp: int, reason: str) -> None:
    reward = max(0, int(reward_xp or 0))
    if reward <= 0:
        return
    user.bonus_xp = int(user.bonus_xp or 0) + reward
    db.add(user)
    week_start = week_start_for_date(dt.datetime.utcnow())
    row = (
        db.query(XpHistory)
        .filter(XpHistory.user_id == user.id, XpHistory.week_start == week_start)
        .one_or_none()
    )
    if not row:
        row = XpHistory(user_id=user.id, week_start=week_start, xp_gained=reward)
        db.add(row)
    else:
        row.xp_gained = int(row.xp_gained or 0) + reward
    db.add(ActivityLog(user_id=user.id, event="bonus_xp_award", meta={"reason": reason, "xp": reward}))


def _raise_project_path_difficulty(steps: list[dict], path_level: int) -> list[dict]:
    if not steps:
        return steps
    progression = ["Beginner", "Intermediate", "Advanced"]
    level_boost = max(0, int(path_level or 1) - 1)
    intensified: list[dict] = []
    for index, step in enumerate(steps):
        next_step = {**step}
        current_difficulty = str(step.get("difficulty") or "Beginner").strip().capitalize()
        try:
            base_index = progression.index(current_difficulty)
        except ValueError:
            base_index = 0
        next_difficulty = progression[min(len(progression) - 1, base_index + min(level_boost, 2))]
        base_xp = int(step.get("reward_xp") or step.get("estimated_xp") or 100)
        xp_boost = level_boost * 35 + index * 10
        next_xp = max(base_xp + xp_boost, base_xp)
        next_step["difficulty"] = next_difficulty
        next_step["reward_xp"] = next_xp
        next_step["estimated_xp"] = next_xp
        current_reason = str(step.get("reason") or step.get("description") or "").strip()
        if level_boost > 0:
            next_step["reason"] = (
                f"{current_reason} This is path level {path_level}, so the expected implementation depth and proof quality are higher."
            ).strip()
        current_logic = str(step.get("progression_logic") or "").strip()
        next_step["progression_logic"] = (
            f"{current_logic} Push this step beyond the previous cycle by improving reliability, completeness, and technical depth."
        ).strip()
        intensified.append(next_step)
    return intensified


def _daily_quest_completed(db: Session, user_id: int, quest_key: str, start: dt.datetime, end: dt.datetime) -> bool:
    if quest_key == "daily_login":
        return (
            db.query(ActivityLog)
            .filter(
                ActivityLog.user_id == user_id,
                ActivityLog.event.in_(["login", "heartbeat"]),
                ActivityLog.created_at >= start,
                ActivityLog.created_at < end,
            )
            .count()
            > 0
        )
    if quest_key == "daily_learning_view":
        return (
            db.query(ActivityLog)
            .filter(
                ActivityLog.user_id == user_id,
                ActivityLog.event.in_(["learning_path_view", "project_learning_path_view"]),
                ActivityLog.created_at >= start,
                ActivityLog.created_at < end,
            )
            .count()
            > 0
        )
    if quest_key == "daily_recompute":
        return (
            db.query(ActivityLog)
            .filter(
                ActivityLog.user_id == user_id,
                ActivityLog.event == "recompute",
                ActivityLog.created_at >= start,
                ActivityLog.created_at < end,
            )
            .count()
            > 0
        )
    return False


def _weekly_challenge_completed(db: Session, user_id: int, challenge_key: str, week_start: dt.datetime) -> bool:
    if challenge_key == "weekly_commit_10":
        commits = (
            db.query(EngagementCommit)
            .filter(EngagementCommit.user_id == user_id, EngagementCommit.week_start == week_start)
            .with_entities(func.coalesce(func.sum(EngagementCommit.commit_count), 0))
            .scalar()
        )
        return int(commits or 0) >= 10
    if challenge_key == "weekly_learning_2":
        done = (
            db.query(LearningProgress)
            .filter(
                LearningProgress.user_id == user_id,
                LearningProgress.status == "done",
                LearningProgress.completed_at >= week_start,
            )
            .count()
        )
        return done >= 2
    if challenge_key == "weekly_cert_1":
        count = (
            db.query(CertificateRecord)
            .filter(
                CertificateRecord.user_id == user_id,
                CertificateRecord.status == "verified",
                CertificateRecord.reviewer_id.isnot(None),
                CertificateRecord.verified_at >= week_start,
            )
            .count()
        )
        return count >= 1
    return False


def _dimension_band(score: int) -> str:
    if score >= 70:
        return "strong"
    if score >= 40:
        return "developing"
    return "gap"


def _build_weekly_digest(db: Session, user: User) -> dict:
    week_start = week_start_for_date(dt.datetime.utcnow())
    commits = (
        db.query(EngagementCommit)
        .filter(EngagementCommit.user_id == user.id, EngagementCommit.week_start == week_start)
        .with_entities(func.coalesce(func.sum(EngagementCommit.commit_count), 0))
        .scalar()
    )
    xp_gained = (
        db.query(XpHistory)
        .filter(XpHistory.user_id == user.id, XpHistory.week_start == week_start)
        .with_entities(func.coalesce(func.sum(XpHistory.xp_gained), 0))
        .scalar()
    )
    completed_steps = (
        db.query(LearningProgress)
        .filter(
            LearningProgress.user_id == user.id,
            LearningProgress.status == "done",
            LearningProgress.completed_at >= week_start,
        )
        .count()
    )
    logs = (
        db.query(ActivityLog)
        .filter(ActivityLog.user_id == user.id, ActivityLog.created_at >= week_start)
        .all()
    )
    active_days = len({(item.created_at.date().isoformat() if item.created_at else "") for item in logs if item.created_at})
    summary = (
        f"This week: {int(commits or 0)} commits, {int(xp_gained or 0)} XP gained, "
        f"{completed_steps} completed learning steps, active for {active_days} day(s)."
    )
    return {
        "username": user.username,
        "week_start": week_start.date().isoformat(),
        "commits": int(commits or 0),
        "xp_gained": int(xp_gained or 0),
        "completed_steps": completed_steps,
        "active_days": active_days,
        "summary": summary,
    }


def _normalize_fcc_status(value: str | None, progress_percent: int) -> str:
    status = (value or "").strip().lower()
    allowed = {"not_started", "in_progress", "done"}
    if status not in allowed:
        status = "done" if int(progress_percent or 0) >= 100 else ("in_progress" if int(progress_percent or 0) > 0 else "not_started")
    if status == "done":
        return "done"
    if status == "not_started" and int(progress_percent or 0) > 0:
        return "in_progress"
    if status == "in_progress" and int(progress_percent or 0) <= 0:
        return "not_started"
    return status


def _fcc_progress_payload(row: FccModuleProgress) -> dict:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "module_key": row.module_key,
        "module_title": row.module_title,
        "status": row.status,
        "progress_percent": int(row.progress_percent or 0),
        "notes": row.notes,
        "certificate_url": row.certificate_url,
        "completed_at": str(row.completed_at) if row.completed_at else None,
        "created_at": str(row.created_at) if row.created_at else None,
        "updated_at": str(row.updated_at) if row.updated_at else None,
    }


def _fcc_progress_summary(rows: list[FccModuleProgress]) -> dict:
    total_modules = len(rows)
    modules_started = sum(1 for row in rows if (row.status or "") in {"in_progress", "done"} or int(row.progress_percent or 0) > 0)
    modules_completed = sum(1 for row in rows if (row.status or "") == "done" or int(row.progress_percent or 0) >= 100)
    overall_progress_percent = int(round(sum(int(row.progress_percent or 0) for row in rows) / total_modules)) if total_modules else 0
    timestamps = [row.updated_at for row in rows if row.updated_at]
    last_updated = max(timestamps) if timestamps else None
    return {
        "overall_progress_percent": max(0, min(100, overall_progress_percent)),
        "modules_started": modules_started,
        "modules_completed": modules_completed,
        "total_modules": total_modules,
        "last_updated_at": str(last_updated) if last_updated else None,
    }


def _normalize_project_stage_status(value: str | None) -> str:
    status = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if status in {"complete", "completed", "complete_stage"}:
        return "complete_stage"
    if status in {"ongoing", "on_going"}:
        return "in_progress"
    allowed = {"not_started", "in_progress", "done"}
    if status not in allowed:
        raise HTTPException(status_code=400, detail="Invalid stage status")
    return status


def _is_project_stage_claim_complete(value: object) -> bool:
    try:
        return _normalize_project_stage_status(str(value or "")) in {"done", "complete_stage"}
    except HTTPException:
        return False


def _project_baseline_key(project_baseline: dict, repo_name: str) -> str:
    clean_name = str(repo_name or "").strip()
    clean_lower = clean_name.lower()
    for key in project_baseline.keys():
        if str(key).strip().lower() == clean_lower:
            return str(key)
    return clean_name


def _serialize_certificate_thread(rows: list[ActivityLog]) -> tuple[list[dict], str | None, str | None]:
    thread: list[dict] = []
    latest_admin_comment_at: str | None = None
    latest_student_reply_at: str | None = None
    for row in rows:
        meta = row.meta or {}
        comment = str(meta.get("comment") or "").strip()
        role = str(meta.get("role") or "").strip().lower()
        if not comment or role not in {"admin", "student"}:
            continue
        updated_at = str(row.created_at) if row.created_at else None
        thread.append(
            {
                "comment": comment,
                "by": str(meta.get("by") or ""),
                "role": role,
                "updated_at": updated_at,
            }
        )
        if role == "admin":
            latest_admin_comment_at = updated_at
        else:
            latest_student_reply_at = updated_at
    return thread, latest_admin_comment_at, latest_student_reply_at


def _certificate_thread_map(db: Session, user_id: int, certificate_ids: list[int]) -> dict[int, dict]:
    clean_ids = [int(item) for item in certificate_ids if int(item) > 0]
    if not clean_ids:
        return {}
    logs = (
        db.query(ActivityLog)
        .filter(
            ActivityLog.user_id == user_id,
            ActivityLog.event.in_(["certificate_admin_comment", "certificate_student_reply"]),
        )
        .order_by(ActivityLog.created_at.asc(), ActivityLog.id.asc())
        .all()
    )
    grouped: dict[int, list[ActivityLog]] = {item: [] for item in clean_ids}
    for row in logs:
        meta = row.meta or {}
        certificate_id = int(meta.get("certificate_id") or 0)
        if certificate_id in grouped:
            grouped[certificate_id].append(row)
    result: dict[int, dict] = {}
    for certificate_id, items in grouped.items():
        thread, latest_admin_comment_at, latest_student_reply_at = _serialize_certificate_thread(items)
        result[certificate_id] = {
            "comment_thread": thread,
            "latest_admin_comment_at": latest_admin_comment_at,
            "latest_student_reply_at": latest_student_reply_at,
        }
    return result


def _certificate_payload(row: CertificateRecord, username: str | None, thread_meta: dict | None = None) -> dict:
    thread_meta = thread_meta or {}
    return {
        "id": row.id,
        "user_id": row.user_id,
        "username": username,
        "title": row.title,
        "provider": row.provider,
        "proof_type": row.proof_type,
        "certificate_url": row.certificate_url,
        "certificate_page_url": row.certificate_page_url,
        "student_note": row.student_note,
        "suggestion_track_id": getattr(row, "suggestion_track_id", None),
        "suggestion_module_url": getattr(row, "suggestion_module_url", None),
        "completion_locked": bool(getattr(row, "completion_locked", False)),
        "completion_reward_xp": getattr(row, "completion_reward_xp", None),
        "rewarded_at": str(getattr(row, "rewarded_at", None)) if getattr(row, "rewarded_at", None) else None,
        "hidden_from_student": bool(getattr(row, "hidden_from_student", False)),
        "status": row.status,
        "reviewer_note": row.reviewer_note,
        "submitted_at": str(row.submitted_at),
        "verified_at": str(getattr(row, "verified_at", None)) if getattr(row, "verified_at", None) else None,
        "comment_thread": thread_meta.get("comment_thread") if isinstance(thread_meta.get("comment_thread"), list) else [],
        "latest_admin_comment_at": thread_meta.get("latest_admin_comment_at"),
        "latest_student_reply_at": thread_meta.get("latest_student_reply_at"),
}


def _normalize_suggestion_track_id(value: str | None) -> str | None:
    clean = str(value or "").strip()
    return clean or None


def _normalize_suggestion_module_url(value: str | None) -> str | None:
    clean = str(value or "").strip()
    return clean or None


def _find_locked_certificate_for_track(
    db: Session,
    user_id: int,
    suggestion_track_id: str | None,
    suggestion_module_url: str | None,
) -> CertificateRecord | None:
    query = db.query(CertificateRecord).filter(
        CertificateRecord.user_id == user_id,
        CertificateRecord.completion_locked.is_(True),
    )
    if suggestion_track_id:
        existing = query.filter(CertificateRecord.suggestion_track_id == suggestion_track_id).order_by(CertificateRecord.submitted_at.desc()).first()
        if existing:
            return existing
    if suggestion_module_url:
        existing = query.filter(CertificateRecord.suggestion_module_url == suggestion_module_url).order_by(CertificateRecord.submitted_at.desc()).first()
        if existing:
            return existing
    return None


def _mark_synced_fcc_certificates_as_done(db: Session, user: User, sync_result: dict) -> None:
    items = list(sync_result.get("items") or [])
    changed = False
    for item in items:
        slug = str(item.get("url") or "").rstrip("/").split("/")[-1].strip().lower()
        mapped = FCC_CERT_MODULE_MAP.get(slug)
        if not mapped:
            continue
        module_key, module_title = mapped
        row = (
            db.query(FccModuleProgress)
            .filter(FccModuleProgress.user_id == user.id, FccModuleProgress.module_key == module_key)
            .one_or_none()
        )
        if not row:
            row = FccModuleProgress(
                user_id=user.id,
                module_key=module_key,
                module_title=module_title,
            )
            db.add(row)
        row.module_title = module_title
        row.status = "done"
        row.progress_percent = 100
        row.certificate_url = str(item.get("url") or "").strip() or row.certificate_url
        row.completed_at = dt.datetime.utcnow()
        changed = True

    if changed:
        db.add(ActivityLog(user_id=user.id, event="fcc_certificate_sync_complete", meta={"found": len(items)}))
        db.commit()





@router.get("/ping")
def ping(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.add(ActivityLog(user_id=current_user.id, event="heartbeat"))
    db.commit()
    has_recommendation_action = (
        db.query(RecommendationAction)
        .filter(
            RecommendationAction.user_id == current_user.id,
            RecommendationAction.action.in_(list(ADOPTED_RECOMMENDATION_ACTIONS)),
        )
        .count()
        > 0
    )
    return {"ok": True, "has_recommendation_action": has_recommendation_action}


@router.post("/logout")
def logout(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    current_user.last_seen = func.now()
    db.add(ActivityLog(user_id=current_user.id, event="logout"))
    db.add(current_user)
    db.commit()
    return {"ok": True}


def _badge_bonus_xp(badges: list[Badge]) -> int:
    return sum(badge_reward_xp(item.rarity) for item in badges if item.claimed)


def _badge_rank_weight(badge: Badge) -> tuple[int, int, int, str]:
    rarity_order = {"legendary": 5, "epic": 4, "rare": 3, "uncommon": 2, "common": 1}
    return (
        1 if badge.claimed else 0,
        1 if badge.achieved else 0,
        rarity_order.get(str(badge.rarity or "").lower(), 0),
        str(badge.label or "").lower(),
    )


def _badge_payload(item: Badge) -> dict:
    visuals = badge_visuals(item.label, item.rarity, item.description)
    reward_xp = badge_reward_xp(item.rarity)
    clean_description = re.sub(r"^\[Category:\s*.+?\]\s*", "", item.description or "").strip()
    return {
        "label": item.label,
        "description": clean_description or item.description,
        "criteria": humanize_badge_criteria(item.criteria),
        "rarity": item.rarity,
        "achieved": item.achieved,
        "claimed": item.claimed,
        "reward_xp": reward_xp,
        **visuals,
    }


def _generated_badge_payload(item: dict) -> dict:
    label = str(item.get("label") or "").strip()
    rarity = str(item.get("rarity") or "common").strip().lower() or "common"
    description = str(item.get("description") or "").strip()
    clean_description = re.sub(r"^\[Category:\s*.+?\]\s*", "", description).strip()
    visuals = badge_visuals(label, rarity, description)
    achieved = bool(item.get("achieved"))
    return {
        "label": label,
        "description": clean_description or description or label,
        "criteria": humanize_badge_criteria(item.get("criteria")),
        "rarity": rarity,
        "achieved": achieved,
        # Fallback display mode: if badge rows were lost, avoid reintroducing
        # a confusing bulk re-claim state for achievements the user already met.
        "claimed": achieved,
        "reward_xp": badge_reward_xp(rarity),
        **visuals,
    }


def _repair_reintroduced_badge_claims(db: Session, user_id: int) -> None:
    already_repaired = (
        db.query(ActivityLog)
        .filter(ActivityLog.user_id == user_id, ActivityLog.event == BADGE_REPAIR_EVENT)
        .count()
        > 0
    )
    if already_repaired:
        return

    claimed_count = (
        db.query(Badge)
        .filter(Badge.user_id == user_id, Badge.claimed.is_(True))
        .count()
    )
    if claimed_count <= 0:
        return

    pending_rows = (
        db.query(Badge)
        .filter(Badge.user_id == user_id, Badge.achieved.is_(True), Badge.claimed.is_(False))
        .all()
    )
    if not pending_rows:
        return

    for row in pending_rows:
        row.claimed = True
        db.add(row)

    db.add(
        ActivityLog(
            user_id=user_id,
            event=BADGE_REPAIR_EVENT,
            meta={"auto_claimed_badge_count": len(pending_rows)},
        )
    )
    db.commit()


def _safe_fetch_commit_streak_days(username: str, token: str | None = None) -> int:
    try:
        return int(fetch_commit_streak_days(username, token=token) or 0)
    except Exception:
        return 0


def _active_repos_last_30_days(repos: list[Repo]) -> int:
    cutoff = dt.datetime.utcnow() - dt.timedelta(days=30)
    count = 0
    for repo in repos:
        last_push = repo.last_push
        if not last_push:
            continue
        try:
            pushed_at = dt.datetime.fromisoformat(str(last_push))
        except ValueError:
            continue
        if pushed_at.tzinfo is not None:
            pushed_at = pushed_at.astimezone(dt.timezone.utc).replace(tzinfo=None)
        if pushed_at >= cutoff:
            count += 1
    return count


def _weekly_commit_rows(db: Session, user_id: int, *, fallback_commits: int) -> list[dict]:
    rows = (
        db.query(EngagementCommit)
        .filter(EngagementCommit.user_id == user_id)
        .order_by(EngagementCommit.week_start.desc())
        .limit(4)
        .all()
    )
    if rows:
        rows = sorted(rows, key=lambda item: item.week_start)
        return [
            {
                "week_start": item.week_start.isoformat() if item.week_start else None,
                "commit_count": int(item.commit_count or 0),
            }
            for item in rows
            if item.week_start
        ]

    return [
        {
            "week_start": week_start_for_date(dt.datetime.utcnow()).isoformat(),
            "commit_count": int(fallback_commits or 0),
        }
    ]


def _skill_domain_payload(practice_dimensions: list[dict]) -> tuple[list[dict], dict | None]:
    competency_levels = build_competency_levels(practice_dimensions)
    domains = [
        {
            "dimension_key": item["dimension_key"],
            "domain": item["dimension"],
            "description": item["description"],
            "score_percent": int(item["score_percent"]),
            "level": item["level"],
            "evidence": item.get("evidence") or [],
        }
        for item in competency_levels
    ]
    domains.sort(key=lambda item: int(item.get("score_percent") or 0), reverse=True)
    focus = next((item for item in domains if int(item.get("score_percent") or 0) > 0), None)
    return domains, focus


def _build_badge_context(
    db: Session,
    user: User,
    *,
    practice_dimensions: list[dict] | None = None,
    streak_days: int | None = None,
) -> dict:
    if practice_dimensions is None:
        rows = db.query(PracticeDimension).filter(PracticeDimension.user_id == user.id).all()
        practice_dimensions = [
            {"label": item.label, "confidence": item.confidence, "evidence": item.evidence}
            for item in rows
        ]

    if streak_days is None:
        streak_days = _safe_fetch_commit_streak_days(user.username, token=user.github_token)

    certificate_verified_count = (
        db.query(CertificateRecord)
        .filter(CertificateRecord.user_id == user.id, CertificateRecord.status == "verified")
        .count()
    )
    certificate_total_count = (
        db.query(CertificateRecord)
        .filter(CertificateRecord.user_id == user.id)
        .count()
    )
    daily_quest_claim_count = (
        db.query(DailyQuestClaim)
        .filter(DailyQuestClaim.user_id == user.id)
        .count()
    )
    weekly_challenge_claim_count = (
        db.query(WeeklyChallengeClaim)
        .filter(WeeklyChallengeClaim.user_id == user.id)
        .count()
    )
    certificate_reward_claimed_count = (
        db.query(CertificateRecord)
        .filter(CertificateRecord.user_id == user.id, CertificateRecord.rewarded_at.isnot(None))
        .count()
    )
    certificate_locked_count = (
        db.query(CertificateRecord)
        .filter(CertificateRecord.user_id == user.id, CertificateRecord.completion_locked.is_(True))
        .count()
    )
    learning_path_completed_count = (
        db.query(ActivityLog)
        .filter(ActivityLog.user_id == user.id, ActivityLog.event == "learning_path_complete")
        .count()
    )
    project_path_claim_count = (
        db.query(ActivityLog)
        .filter(ActivityLog.user_id == user.id, ActivityLog.event == "project_learning_path_claim")
        .count()
    )
    portfolio_settings = (
        db.query(PortfolioSettings)
        .filter(PortfolioSettings.user_id == user.id)
        .one_or_none()
    )
    has_portfolio_settings = portfolio_settings is not None
    learning_path_steps_count = 0
    project_path_started_count = 0
    project_path_completed_count = 0
    project_stage_completed_count = 0
    if portfolio_settings is not None:
        learning_path_baseline = portfolio_settings.learning_path_baseline or {}
        if isinstance(learning_path_baseline, dict):
            baseline_steps = learning_path_baseline.get("steps")
            if isinstance(baseline_steps, list):
                learning_path_steps_count = len(baseline_steps)

        project_baseline = portfolio_settings.project_learning_path_baseline or {}
        if isinstance(project_baseline, dict):
            for entry in project_baseline.values():
                if not isinstance(entry, dict):
                    continue
                project_path_started_count += 1
                if bool(entry.get("repo_completed")):
                    project_path_completed_count += 1
                stage_status_overrides = entry.get("stage_status_overrides")
                if isinstance(stage_status_overrides, dict):
                    project_stage_completed_count += sum(
                        1 for value in stage_status_overrides.values() if _is_project_stage_claim_complete(value)
                    )

    return {
        "streak_days": int(streak_days or 0),
        "practice_dimensions": practice_dimensions,
        "certificate_verified_count": certificate_verified_count,
        "certificate_total_count": certificate_total_count,
        "certificate_reward_claimed_count": certificate_reward_claimed_count,
        "certificate_locked_count": certificate_locked_count,
        "daily_quest_claim_count": daily_quest_claim_count,
        "weekly_challenge_claim_count": weekly_challenge_claim_count,
        "learning_path_completed_count": learning_path_completed_count,
        "learning_path_steps_count": learning_path_steps_count,
        "project_path_started_count": project_path_started_count,
        "project_path_completed_count": project_path_completed_count,
        "project_path_claim_count": project_path_claim_count,
        "project_stage_completed_count": project_stage_completed_count,
        "has_portfolio_settings": has_portfolio_settings,
    }


def _sync_badges(db: Session, user_id: int, generated_badges: list[dict]) -> None:
    upsert_badges(db, user_id, generated_badges, preserve_achieved=True, clear_claimed_when_unachieved=False)


def _repo_summaries_for_inference(repos: list[Repo]) -> list[dict]:
    return [
        {
            "name": repo.name,
            "description": repo.description,
            "language": repo.language,
            "languages": repo.languages,
            "language_bytes": repo.language_bytes,
            "stars": repo.stars,
            "topics": repo.topics,
            "code_signals": repo.code_signals or {},
            "last_push": repo.last_push,
            "commit_count": repo.commit_count,
        }
        for repo in repos
    ]


def _compute_portfolio_completeness(
    user: User,
    repos: list[Repo],
    settings: PortfolioSettings | None,
) -> int:
    social_links = (settings.social_links or {}) if settings and isinstance(settings.social_links, dict) else {}
    about_text = (settings.bio or user.bio or "").strip() if settings else (user.bio or "").strip()
    tech_stack = [str(item).strip() for item in (social_links.get("tech_stack") or []) if str(item).strip()]
    contact_values = [
        str(social_links.get("email") or "").strip(),
        str(social_links.get("linkedin") or "").strip(),
        str(social_links.get("phone") or "").strip(),
    ]
    education_history = [item for item in (social_links.get("education_history") or []) if isinstance(item, dict)]
    job_experience = [item for item in (social_links.get("job_experience") or []) if isinstance(item, dict)]
    featured_repos = [str(item).strip() for item in ((settings.featured_repos or []) if settings else []) if str(item).strip()]

    score = 0
    if (user.display_name or "").strip():
        score += 10
    if (user.student_id or "").strip():
        score += 10
    if (user.program or "").strip():
        score += 10
    if (user.year_level or "").strip():
        score += 10
    if about_text:
        score += 15
    if repos:
        score += 20
    if tech_stack:
        score += 10
    if any(contact_values):
        score += 5
    if education_history or job_experience:
        score += 5
    if featured_repos:
        score += 5

    return min(100, score)


def _learning_path_signature(steps: list[dict]) -> str:
    titles = [str(step.get("title") or "").strip().lower() for step in steps if step.get("title")]
    payload = "|".join(titles)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _issue_learning_path_certificate(db: Session, user: User, steps: list[dict]) -> bool:
    signature = _learning_path_signature(steps)
    existing = (
        db.query(CertificateRecord)
        .filter(
            CertificateRecord.user_id == user.id,
            CertificateRecord.provider == "DevPath",
            CertificateRecord.certificate_url.contains(signature),
        )
        .first()
    )
    if existing:
        return False

    issued_on = dt.datetime.utcnow().date().isoformat()
    title = f"Learning Path Completion ({issued_on})"
    certificate_url = f"{settings.frontend_url}/certificates?user={user.username}&ref=learning-path-{signature}"
    db.add(
        CertificateRecord(
            user_id=user.id,
            title=title,
            provider="DevPath",
            certificate_url=certificate_url,
            status="verified",
            reviewer_note=f"Auto-issued after learning path completion. Signature: {signature}",
            verified_at=dt.datetime.utcnow(),
        )
    )
    db.add(
        ActivityLog(
            user_id=user.id,
            event="learning_path_complete",
            meta={"signature": signature, "step_count": len(steps)},
        )
    )
    return True


def _sync_inference_from_repo_signals(
    db: Session,
    user: User,
    repos: list[Repo],
    *,
    force: bool = False,
) -> tuple[list[PracticeDimension], list[CareerSuggestion], list[dict]]:
    summaries = _repo_summaries_for_inference(repos)
    practice_rows = db.query(PracticeDimension).filter(PracticeDimension.user_id == user.id).all()
    career_rows = db.query(CareerSuggestion).filter(CareerSuggestion.user_id == user.id).all()

    should_refresh = force or not practice_rows or not career_rows
    if not should_refresh:
        return practice_rows, career_rows, summaries

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
    db.commit()
    practice_rows = db.query(PracticeDimension).filter(PracticeDimension.user_id == user.id).all()
    career_rows = db.query(CareerSuggestion).filter(CareerSuggestion.user_id == user.id).all()
    return practice_rows, career_rows, summaries


@router.get("/user/{username}", response_model=UserResponse)
def get_user(
    username: str,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    if (username or "").strip().lower() == "me":
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing token")
        token = authorization.replace("Bearer ", "", 1)
        try:
            payload = decode_access_token(token, settings.jwt_secret, settings.jwt_issuer)
        except ValueError:
            raise HTTPException(status_code=401, detail="Invalid token")
        subject = payload.get("sub")
        try:
            user_id = int(str(subject))
        except (TypeError, ValueError):
            raise HTTPException(status_code=401, detail="Invalid token")
        user = db.query(User).filter(User.id == user_id).one_or_none()
    else:
        user = db.query(User).filter(User.username == username).one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    _repair_reintroduced_badge_claims(db, user.id)

    repos = db.query(Repo).filter(Repo.user_id == user.id).all()
    streak_days = _safe_fetch_commit_streak_days(user.username, token=user.github_token)
    badge_context = _build_badge_context(db, user, streak_days=streak_days)
    gamification = compute_xp_and_badges([repo.__dict__ for repo in repos], context=badge_context)
    practice_rows = db.query(PracticeDimension).filter(PracticeDimension.user_id == user.id).all()
    career_rows = db.query(CareerSuggestion).filter(CareerSuggestion.user_id == user.id).all()
    practice_payload = [{"label": item.label, "confidence": item.confidence, "evidence": item.evidence} for item in practice_rows]
    skill_domains, focus_domain = _skill_domain_payload(practice_payload)

    badge_rows = db.query(Badge).filter(Badge.user_id == user.id).all()
    badge_payloads = [_badge_payload(item) for item in badge_rows]
    if not badge_payloads:
        badge_payloads = [_generated_badge_payload(item) for item in gamification.badges]
    bonus_xp = _badge_bonus_xp(badge_rows)
    total_xp = gamification.xp + bonus_xp + int(user.bonus_xp or 0)
    level = level_from_xp(total_xp)
    next_level_xp = next_level_xp_for_total(total_xp)
    has_recommendation_action = (
        db.query(RecommendationAction)
        .filter(
            RecommendationAction.user_id == user.id,
            RecommendationAction.action.in_(list(ADOPTED_RECOMMENDATION_ACTIONS)),
        )
        .count()
        > 0
    )

    total_commits = sum(int(repo.commit_count or 0) for repo in repos)
    weekly_commits = _weekly_commit_rows(db, user.id, fallback_commits=total_commits)
    weekly_avg = float(sum(int(item.get("commit_count") or 0) for item in weekly_commits) / max(1, len(weekly_commits)))
    portfolio_settings = (
        db.query(PortfolioSettings).filter(PortfolioSettings.user_id == user.id).one_or_none()
    )
    portfolio_completeness = _compute_portfolio_completeness(user, repos, portfolio_settings)
    frequency = {
        "total_commits": total_commits,
        "repo_count": len(repos),
        "active_repos_30d": _active_repos_last_30_days(repos),
        "weekly_commits": weekly_commits,
        "weekly_commit_average": weekly_avg,
        "streak_days": streak_days,
    }

    return {
        "profile": {
            "username": user.username,
            "display_name": user.display_name,
            "bio": user.bio,
            "student_id": user.student_id,
            "program": user.program,
            "year_level": user.year_level,
            "career_interest": user.career_interest,
            "preferred_learning_style": user.preferred_learning_style,
            "target_role": user.target_role,
            "target_certifications": list(user.target_certifications or []),
            "avatar_url": user.avatar_url,
            "level": level,
            "xp": total_xp,
            "next_level_xp": next_level_xp,
            "streak_days": streak_days,
            "portfolio_completeness": portfolio_completeness,
            "has_recommendation_action": has_recommendation_action,
            "is_verified": bool(user.is_verified),
            "verified_at": str(user.verified_at) if user.verified_at else None,
        },
        "practice_dimensions": practice_payload,
        "career_suggestions": [
            {"title": item.title, "confidence": item.confidence, "reasoning": item.reasoning}
            for item in career_rows
        ],
        "skill_domains": skill_domains,
        "focus_domain": focus_domain,
        "frequency": frequency,
        "badges": badge_payloads,
        "repos": [
            {
                "name": repo.name,
                "description": repo.description,
                "language": repo.language,
                "languages": repo.languages,
                "language_bytes": repo.language_bytes,
                "code_signals": repo.code_signals or {},
                "stars": repo.stars,
                "last_push": repo.last_push if repo.last_push else None,
                "commit_count": repo.commit_count,
            }
            for repo in repos
        ],
    }


@router.put("/user/settings", response_model=PortfolioResponse)
def update_settings(
    payload: PortfolioSettingsIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not payload:
        raise HTTPException(status_code=400, detail="Missing payload")

    settings = (
        db.query(PortfolioSettings).filter(PortfolioSettings.user_id == current_user.id).one_or_none()
    )
    if not settings:
        settings = PortfolioSettings(user_id=current_user.id)
        db.add(settings)

    updates = payload.model_dump(exclude_unset=True)
    if "show_sections" in updates:
        current = settings.show_sections or {}
        merged = {**current, **(updates.get("show_sections") or {})}
        updates["show_sections"] = merged

    social_links_update = updates.get("social_links")
    if isinstance(social_links_update, dict):
        if "student_id" in social_links_update:
            current_user.student_id = str(social_links_update.get("student_id") or "").strip() or None
        if "program" in social_links_update:
            current_user.program = str(social_links_update.get("program") or "").strip() or None
        if "year_level" in social_links_update:
            current_user.year_level = str(social_links_update.get("year_level") or "").strip() or None

    for field, value in updates.items():
        setattr(settings, field, value)

    db.add(ActivityLog(user_id=current_user.id, event="profile_update"))
    db.commit()
    db.refresh(settings)

    response = get_user(current_user.username, db=db)
    return {
        **response,
        "settings": {
            "theme": settings.theme,
            "theme_light": settings.theme_light,
            "theme_dark": settings.theme_dark,
            "section_order": settings.section_order,
            "show_sections": settings.show_sections or {"badges": True, "repos": True, "preview_dark": False},
            "featured_repos": settings.featured_repos,
            "featured_badges": settings.featured_badges,
            "social_links": settings.social_links,
            "bio": settings.bio,
            "cover_image": settings.cover_image,
            "is_public": settings.is_public,
        },
    }


@router.post("/register", response_model=UserResponse)
def register(payload: RegistrationIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    display_name = (payload.display_name or "").strip()
    bio = (payload.bio or "").strip()
    student_id = (payload.student_id or "").strip()
    program = (payload.program or "").strip()
    year_level = (payload.year_level or "").strip()

    if not display_name:
        raise HTTPException(status_code=400, detail="Display name is required")
    if not student_id:
        raise HTTPException(status_code=400, detail="Student ID is required")
    if not program:
        raise HTTPException(status_code=400, detail="Program is required")
    if not year_level:
        raise HTTPException(status_code=400, detail="Year level is required")

    if payload.display_name is not None:
        current_user.display_name = display_name
    if payload.bio is not None:
        current_user.bio = bio
    if payload.student_id is not None:
        current_user.student_id = student_id or None
    if payload.program is not None:
        current_user.program = program or None
    if payload.year_level is not None:
        current_user.year_level = year_level or None
    if payload.career_interest is not None:
        current_user.career_interest = payload.career_interest.strip() or None
    if payload.preferred_learning_style is not None:
        current_user.preferred_learning_style = payload.preferred_learning_style.strip() or None
    if payload.target_role is not None:
        current_user.target_role = payload.target_role.strip() or None
    if payload.target_certifications is not None:
        cleaned = [str(item).strip() for item in payload.target_certifications if str(item).strip()]
        current_user.target_certifications = cleaned

    if (current_user.role or "student") == "student":
        current_user.is_verified = True
        current_user.verified_at = dt.datetime.utcnow()

    db.add(ActivityLog(user_id=current_user.id, event="profile_update"))
    db.commit()
    db.refresh(current_user)
    return get_user(current_user.username, db=db)


@router.post("/user/recompute", response_model=UserResponse)
def recompute_insights(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    existing_repos = db.query(Repo).filter(Repo.user_id == current_user.id).all()
    existing_repo_map = {repo.name: repo for repo in existing_repos}
    try:
        if current_user.github_token:
            repos_raw = fetch_repos(current_user.github_token)
        else:
            repos_raw = fetch_public_repos(current_user.username)
        summaries = []
        for repo in repos_raw:
            repo_name = str(repo.get("name") or "").strip()
            if not repo_name:
                continue
            full_name = repo.get("full_name", "") or f"{current_user.username}/{repo_name}"
            fallback_repo = existing_repo_map.get(repo_name)

            if current_user.github_token:
                try:
                    languages = fetch_repo_languages(current_user.github_token, full_name)
                except Exception:
                    languages = []
                if not languages and fallback_repo:
                    languages = fallback_repo.languages or []
                try:
                    language_bytes = fetch_repo_language_bytes(current_user.github_token, full_name)
                except Exception:
                    language_bytes = {}
                if not language_bytes and fallback_repo:
                    language_bytes = fallback_repo.language_bytes or {}
            else:
                try:
                    languages = fetch_public_repo_languages(full_name)
                except Exception:
                    languages = []
                if not languages and fallback_repo:
                    languages = fallback_repo.languages or []
                try:
                    language_bytes = fetch_public_repo_language_bytes(full_name)
                except Exception:
                    language_bytes = {}
                if not language_bytes and fallback_repo:
                    language_bytes = fallback_repo.language_bytes or {}
            try:
                commit_count = fetch_repo_commit_count(
                    full_name,
                    current_user.username,
                    token=current_user.github_token,
                )
            except Exception:
                commit_count = int(getattr(fallback_repo, "commit_count", 0) or 0)

            summaries.append(
                summarize_repo(
                    repo,
                    languages,
                    commit_count=commit_count,
                    language_bytes=language_bytes,
                )
            )

        db.query(Repo).filter(Repo.user_id == current_user.id).delete(synchronize_session=False)
        for repo in summaries:
            db.add(Repo(user_id=current_user.id, **repo))
    except Exception:
        # Fallback to last synced repos when GitHub is temporarily unavailable.
        summaries = _repo_summaries_for_inference(existing_repos)

    inference = infer_practice_and_careers(summaries)
    db.query(PracticeDimension).filter(PracticeDimension.user_id == current_user.id).delete()
    for item in inference.get("practice_dimensions", []):
        db.add(
            PracticeDimension(
                user_id=current_user.id,
                label=item["label"],
                confidence=item["confidence"],
                evidence=item.get("evidence", []),
            )
        )
    db.query(CareerSuggestion).filter(CareerSuggestion.user_id == current_user.id).delete()
    for item in inference.get("career_suggestions", []):
        db.add(
            CareerSuggestion(
                user_id=current_user.id,
                title=item["title"],
                confidence=item["confidence"],
                reasoning=item["reasoning"],
            )
        )
    practice_for_badges = [
        {"label": item["label"], "confidence": item["confidence"], "evidence": item.get("evidence", [])}
        for item in inference.get("practice_dimensions", [])
    ]
    badge_context = _build_badge_context(
        db,
        current_user,
        practice_dimensions=practice_for_badges,
        streak_days=_safe_fetch_commit_streak_days(current_user.username, token=current_user.github_token),
    )
    gamification = compute_xp_and_badges(summaries, context=badge_context)
    _sync_badges(db, current_user.id, gamification.badges)

    db.add(ActivityLog(user_id=current_user.id, event="recompute"))
    db.commit()
    try:
        refresh_engagement(db, current_user)
    except Exception:
        pass
    return get_user(current_user.username, db=db)


@router.post("/user/claim-badges", response_model=UserResponse)
def claim_badges(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    updated_rows = db.query(Badge).filter(
        Badge.user_id == current_user.id, Badge.achieved.is_(True), Badge.claimed.is_(False)
    ).update({Badge.claimed: True})
    db.commit()
    return get_user(current_user.username, db=db)


@router.get("/portfolio/{username}", response_model=PortfolioResponse)
def get_portfolio(username: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    settings = db.query(PortfolioSettings).filter(PortfolioSettings.user_id == user.id).one_or_none()
    if not settings or not settings.is_public:
        raise HTTPException(status_code=404, detail="Portfolio not public")

    response = get_user(username, db=db)
    return {
        **response,
        "settings": {
            "theme": settings.theme,
            "theme_light": settings.theme_light,
            "theme_dark": settings.theme_dark,
            "section_order": settings.section_order,
            "show_sections": settings.show_sections or {"badges": True, "repos": True, "preview_dark": False},
            "featured_repos": settings.featured_repos,
            "featured_badges": settings.featured_badges,
            "social_links": settings.social_links,
            "bio": settings.bio,
            "cover_image": settings.cover_image,
            "is_public": settings.is_public,
        },
    }


@router.get("/user/me/portfolio", response_model=PortfolioResponse)
def get_owner_portfolio(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    settings = (
        db.query(PortfolioSettings).filter(PortfolioSettings.user_id == current_user.id).one_or_none()
    )
    if not settings:
        settings = PortfolioSettings(user_id=current_user.id)
        db.add(settings)
        db.commit()
        db.refresh(settings)

    response = get_user(current_user.username, db=db)
    return {
        **response,
        "settings": {
            "theme": settings.theme,
            "theme_light": settings.theme_light,
            "theme_dark": settings.theme_dark,
            "section_order": settings.section_order,
            "show_sections": settings.show_sections or {"badges": True, "repos": True, "preview_dark": False},
            "featured_repos": settings.featured_repos,
            "featured_badges": settings.featured_badges,
            "social_links": settings.social_links,
            "bio": settings.bio,
            "cover_image": settings.cover_image,
            "is_public": settings.is_public,
        },
    }


@router.post("/user/portfolio/generate-summary")
def generate_portfolio_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    settings_row = _get_or_create_portfolio_settings(db, current_user.id)
    repos = db.query(Repo).filter(Repo.user_id == current_user.id).order_by(Repo.commit_count.desc(), Repo.stars.desc(), Repo.name.asc()).all()
    practice_rows = db.query(PracticeDimension).filter(PracticeDimension.user_id == current_user.id).all()
    career_rows = (
        db.query(CareerSuggestion)
        .filter(CareerSuggestion.user_id == current_user.id)
        .order_by(CareerSuggestion.confidence.desc(), CareerSuggestion.title.asc())
        .all()
    )

    social_links = settings_row.social_links or {}
    manual_stack = social_links.get("tech_stack") if isinstance(social_links, dict) else []
    tech_stack = [str(item).strip() for item in (manual_stack or []) if str(item).strip()]
    if not tech_stack:
        tech_stack = _portfolio_signal_labels(repos, limit=6)

    profile_payload = {
        "username": current_user.username,
        "display_name": current_user.display_name,
        "program": current_user.program,
        "year_level": current_user.year_level,
        "career_interest": current_user.career_interest,
        "target_role": current_user.target_role,
        "preferred_learning_style": current_user.preferred_learning_style,
    }
    repo_payload = [
        {
            "name": repo.name,
            "description": repo.description,
            "language": repo.language,
            "languages": repo.languages or [],
            "topics": repo.topics or [],
            "commit_count": repo.commit_count,
            "code_signals": repo.code_signals or {},
        }
        for repo in repos[:8]
    ]
    practice_payload = [
        {"label": row.label, "confidence": row.confidence, "evidence": row.evidence or []}
        for row in sorted(practice_rows, key=lambda item: int(item.confidence or 0), reverse=True)[:3]
    ]
    career_payload = [
        {"title": row.title, "confidence": row.confidence, "reasoning": row.reasoning}
        for row in career_rows[:2]
    ]

    summary = llm_refiner.generate_portfolio_summary(
        profile=profile_payload,
        repos=repo_payload,
        practice_dimensions=practice_payload,
        career_suggestions=career_payload,
        tech_stack=tech_stack,
    )
    if not summary:
        summary = _fallback_portfolio_summary(
            user=current_user,
            repos=repos,
            practice_rows=practice_rows,
            career_rows=career_rows,
            tech_stack=tech_stack,
        )

    db.add(ActivityLog(user_id=current_user.id, event="portfolio_summary_generate"))
    db.commit()
    return {"summary": summary}


@router.get("/user/me")
def get_me(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    has_recommendation_action = (
        db.query(RecommendationAction)
        .filter(
            RecommendationAction.user_id == current_user.id,
            RecommendationAction.action.in_(list(ADOPTED_RECOMMENDATION_ACTIONS)),
        )
        .count()
        > 0
    )
    return {
        "id": current_user.id,
        "username": current_user.username,
        "has_recommendation_action": has_recommendation_action,
    }


def _get_or_create_portfolio_settings(db: Session, user_id: int) -> PortfolioSettings:
    settings_row = db.query(PortfolioSettings).filter(PortfolioSettings.user_id == user_id).one_or_none()
    if settings_row:
        return settings_row
    settings_row = PortfolioSettings(user_id=user_id)
    db.add(settings_row)
    db.commit()
    db.refresh(settings_row)
    return settings_row


def _portfolio_signal_labels(repos: list[Repo], limit: int = 5) -> list[str]:
    counts: dict[str, int] = {}
    for repo in repos:
        values = list(repo.languages or [])
        if repo.language:
            values.append(str(repo.language))
        frameworks = (repo.code_signals or {}).get("frameworks") or []
        values.extend([str(item) for item in frameworks if str(item).strip()])
        for raw in values:
            label = str(raw or "").strip()
            if not label or label.lower() == "unknown":
                continue
            counts[label] = counts.get(label, 0) + 1
    return [label for label, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]]


def _join_labels(items: list[str]) -> str:
    cleaned = [str(item).strip() for item in items if str(item).strip()]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    if len(cleaned) == 2:
        return f"{cleaned[0]} and {cleaned[1]}"
    return f"{', '.join(cleaned[:-1])}, and {cleaned[-1]}"


def _fallback_portfolio_summary(
    *,
    user: User,
    repos: list[Repo],
    practice_rows: list[PracticeDimension],
    career_rows: list[CareerSuggestion],
    tech_stack: list[str],
) -> str:
    academic_bits = [str(user.program or "").strip(), str(user.year_level or "").strip()]
    academic_bits = [item for item in academic_bits if item]
    opener = "I am a student developer"
    if academic_bits:
        opener = f"I am a {' '.join(academic_bits)} student developer"

    stack_text = _join_labels(tech_stack[:4])
    if stack_text:
        opener += f" building projects with {stack_text}"

    sentences = [f"{opener}."]

    strengths = [
        row.label
        for row in sorted(practice_rows, key=lambda item: int(item.confidence or 0), reverse=True)[:2]
        if str(row.label or "").strip()
    ]
    repo_names = [str(repo.name or "").strip() for repo in repos[:2] if str(repo.name or "").strip()]
    detail_bits: list[str] = []
    if strengths:
        detail_bits.append(f"my strongest work is in {_join_labels(strengths)}")
    if repo_names:
        detail_bits.append(f"through repositories such as {_join_labels(repo_names)}")
    if detail_bits:
        sentences.append(f"Based on my portfolio, {' '.join(detail_bits)}.")

    target_role = str(user.target_role or "").strip()
    suggested_role = str(career_rows[0].title if career_rows else "").strip()
    role_text = target_role or suggested_role
    if role_text:
        sentences.append(
            f"I am currently strengthening this portfolio toward a {role_text} path by improving project quality, implementation depth, and real-world readiness."
        )

    return " ".join(sentences[:3]).strip()


@router.get("/leaderboard", response_model=list[LeaderboardEntryOut])
def get_leaderboard(db: Session = Depends(get_db)):
    users = db.query(User).filter(User.role == "student").all()
    entry_rows: list[tuple[LeaderboardEntryOut, list[Badge]]] = []
    current_week = week_start_for_date(dt.datetime.utcnow())
    last_week = current_week - dt.timedelta(weeks=1)
    for user in users:
        repos = db.query(Repo).filter(Repo.user_id == user.id).all()
        gamification = compute_xp_and_badges([repo.__dict__ for repo in repos])
        badge_rows = db.query(Badge).filter(Badge.user_id == user.id).all()
        total_xp = gamification.xp + _badge_bonus_xp(badge_rows) + int(user.bonus_xp or 0)
        level = level_from_xp(total_xp)
        next_level_xp = next_level_xp_for_total(total_xp)
        runway_remaining_xp = max(0, next_level_xp - total_xp)
        weekly_xp = (
            db.query(XpHistory)
            .filter(XpHistory.user_id == user.id, XpHistory.week_start == current_week)
            .with_entities(func.coalesce(func.sum(XpHistory.xp_gained), 0))
            .scalar()
        )
        last_week_xp = (
            db.query(XpHistory)
            .filter(XpHistory.user_id == user.id, XpHistory.week_start == last_week)
            .with_entities(func.coalesce(func.sum(XpHistory.xp_gained), 0))
            .scalar()
        )
        delta = int(weekly_xp or 0) - int(last_week_xp or 0)
        entry_rows.append(
            (
                LeaderboardEntryOut(
                    id=user.id,
                    username=user.username,
                    avatar_url=user.avatar_url,
                    program=user.program,
                    year_level=user.year_level,
                    level=level,
                    xp=total_xp,
                    runway_xp=total_xp,
                    runway_remaining_xp=runway_remaining_xp,
                    delta=f"{'+' if delta >= 0 else ''}{delta} XP",
                    badge_count=len(badge_rows),
                ),
                badge_rows,
            )
        )
    entry_rows.sort(key=lambda item: item[0].xp, reverse=True)
    entries: list[LeaderboardEntryOut] = []
    badge_limits = [7, 5, 4]
    for index, (entry, badge_rows) in enumerate(entry_rows):
        badge_stack_limit = badge_limits[index] if index < len(badge_limits) else 4
        badge_rows_sorted = sorted(badge_rows, key=_badge_rank_weight, reverse=True)
        entry.badge_stack = [
            LeaderboardBadgeOut(
                label=item["label"],
                rarity=item["rarity"],
                medal_icon=item.get("medal_icon"),
                achieved=bool(item["achieved"]),
                claimed=bool(item["claimed"]),
            )
            for item in [_badge_payload(row) for row in badge_rows_sorted[:badge_stack_limit]]
        ]
        entries.append(entry)
    return entries


@router.get("/learning-path/{username}", response_model=LearningPathResponse)
def get_learning_path(
    username: str,
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.username == username).one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    db.add(ActivityLog(user_id=user.id, event="learning_path_view"))
    db.commit()

    portfolio_settings = _get_or_create_portfolio_settings(db, user.id)
    repos = db.query(Repo).filter(Repo.user_id == user.id).all()
    practice_rows = db.query(PracticeDimension).filter(PracticeDimension.user_id == user.id).all()
    inference_summaries = _repo_summaries_for_inference(repos)
    summaries = [
        {
            "name": item.get("name"),
            "description": item.get("description"),
            "language": item.get("language"),
            "languages": item.get("languages"),
            "topics": item.get("topics"),
            "code_signals": item.get("code_signals") or {},
            "commit_count": item.get("commit_count"),
        }
        for item in inference_summaries
    ]
    detected_skills = []
    project_keywords = []
    for repo in summaries:
        langs = repo.get("languages") or []
        if isinstance(langs, list):
            detected_skills.extend([str(lang) for lang in langs if lang])
        if repo.get("language"):
            detected_skills.append(str(repo.get("language")))
        project_keywords.extend([str(topic) for topic in (repo.get("topics") or []) if topic])
        code_signals = repo.get("code_signals") or {}
        project_keywords.extend([str(keyword) for keyword in (code_signals.get("keywords") or []) if keyword])
        detected_skills.extend([str(framework) for framework in (code_signals.get("frameworks") or []) if framework])
        project_keywords.extend([str(repo.get("name") or ""), str(repo.get("description") or "")])

    practice_dimensions = [
        {"label": item.label, "confidence": item.confidence, "evidence": item.evidence}
        for item in practice_rows
    ]

    competency_levels = build_competency_levels(practice_dimensions)
    skill_gaps = identify_skill_gaps(competency_levels)
    signals = build_signal_set(summaries, include_repo_identity=False)
    signals.add(f"personalization:{username}")
    baseline_payload = portfolio_settings.learning_path_baseline or []
    baseline_signals_list: list[str] = []
    cached_signals_list: list[str] = []
    cached_steps: list[dict] | None = None
    if isinstance(baseline_payload, dict):
        baseline_signals_list = list(baseline_payload.get("baseline_signals") or [])
        cached_signals_list = list(baseline_payload.get("latest_signals") or baseline_signals_list)
        raw_steps = baseline_payload.get("steps")
        if isinstance(raw_steps, list):
            cached_steps = raw_steps
    else:
        baseline_signals_list = list(baseline_payload or [])
        cached_signals_list = list(baseline_signals_list)

    baseline = set(baseline_signals_list)
    steps: list[dict]
    if not baseline:
        try:
            steps = infer_learning_path(
                summaries,
                detected_skills=detected_skills,
                project_keywords=project_keywords,
                practice_dimensions=practice_dimensions,
                personalization_key=username,
            )
        except Exception:
            steps = generate_personalized_learning_path(competency_levels, summaries)
        portfolio_settings.learning_path_baseline = {
            "baseline_signals": list(signals),
            "latest_signals": list(signals),
            "steps": steps,
        }
        db.commit()
        steps_with_status = [{**step, "status": "todo"} for step in steps]
        return {
            "username": user.username,
            "steps": steps_with_status,
            "progress_percent": 0,
            "competency_levels": competency_levels,
            "skill_gaps": skill_gaps,
        }

    if cached_steps and set(cached_signals_list) == set(signals):
        steps = cached_steps
    else:
        try:
            steps = infer_learning_path(
                summaries,
                detected_skills=detected_skills,
                project_keywords=project_keywords,
                practice_dimensions=practice_dimensions,
                personalization_key=username,
            )
        except Exception:
            steps = generate_personalized_learning_path(competency_levels, summaries)
        portfolio_settings.learning_path_baseline = {
            "baseline_signals": baseline_signals_list,
            "latest_signals": list(signals),
            "steps": steps,
        }
        db.commit()

    new_signals = signals - baseline
    steps, progress_percent = annotate_steps_with_status(steps, new_signals)
    for step in steps:
        title = step.get("title")
        if not title:
            continue
        existing = (
            db.query(LearningProgress)
            .filter(LearningProgress.user_id == user.id, LearningProgress.learning_step == title)
            .one_or_none()
        )
        status = step.get("status") or "todo"
        if existing and existing.status == "done":
            status = "done"
            step["status"] = "done"
        if not existing:
            db.add(
                LearningProgress(
                    user_id=user.id,
                    learning_step=title,
                    status=status,
                    completed_at=dt.datetime.utcnow() if status == "done" else None,
                )
            )
        else:
            existing.status = status
            if status == "done" and existing.completed_at is None:
                existing.completed_at = dt.datetime.utcnow()
    completed_steps = sum(1 for step in steps if (step.get("status") or "todo") == "done")
    progress_percent = int((completed_steps / len(steps)) * 100) if steps else 0
    path_completed = bool(steps) and completed_steps == len(steps)
    if path_completed:
        _issue_learning_path_certificate(db, user, steps)
        portfolio_settings.learning_path_baseline = []
        db.query(LearningProgress).filter(LearningProgress.user_id == user.id).delete()
        db.commit()
        try:
            steps = infer_learning_path(
                summaries,
                detected_skills=detected_skills,
                project_keywords=project_keywords,
                practice_dimensions=practice_dimensions,
                personalization_key=username,
            )
        except Exception:
            steps = generate_personalized_learning_path(competency_levels, summaries)
        signals = build_signal_set(summaries, include_repo_identity=False)
        portfolio_settings.learning_path_baseline = {
            "baseline_signals": list(signals),
            "latest_signals": list(signals),
            "steps": steps,
        }
        db.commit()
        steps_with_status = [{**step, "status": "todo"} for step in steps]
        return {
            "username": user.username,
            "steps": steps_with_status,
            "progress_percent": 0,
            "competency_levels": competency_levels,
            "skill_gaps": skill_gaps,
        }

    db.commit()
    return {
        "username": user.username,
        "steps": steps,
        "progress_percent": progress_percent,
        "competency_levels": competency_levels,
        "skill_gaps": skill_gaps,
    }


@router.get("/curriculum-map/{username}", response_model=CurriculumMapOut)
def get_curriculum_map(username: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    practice_rows = db.query(PracticeDimension).filter(PracticeDimension.user_id == user.id).all()
    practice_dimensions = [
        {"label": item.label, "confidence": item.confidence, "evidence": item.evidence}
        for item in practice_rows
    ]
    competency_levels = build_competency_levels(practice_dimensions)
    score_by_key = {item["dimension_key"]: int(item["score_percent"]) for item in competency_levels}
    name_by_key = {item["dimension_key"]: item["dimension"] for item in competency_levels}

    subjects = []
    heatmap = []
    for subject in CURRICULUM_SUBJECTS:
        focus_key = subject["focus_dimension_key"]
        coverage = max(0, min(100, score_by_key.get(focus_key, 0)))
        band = _dimension_band(coverage)
        status = "Aligned" if band == "strong" else "Developing" if band == "developing" else "Needs Focus"
        subjects.append(
            {
                **subject,
                "focus_dimension": name_by_key.get(focus_key, focus_key.replace("_", " ").title()),
                "coverage_percent": coverage,
                "status": status,
            }
        )
        for dimension in competency_levels:
            cell_score = coverage if dimension["dimension_key"] == focus_key else int(max(0, dimension["score_percent"] - 15))
            heatmap.append(
                {
                    "subject_code": subject["code"],
                    "dimension_key": dimension["dimension_key"],
                    "dimension": dimension["dimension"],
                    "score_percent": max(0, min(100, cell_score)),
                    "band": _dimension_band(cell_score),
                }
            )

    return {"username": user.username, "subjects": subjects, "heatmap": heatmap}


@router.get("/recommendations/v2/{username}", response_model=RuleRecommendationListOut)
def get_rule_recommendations(username: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    practice_rows = db.query(PracticeDimension).filter(PracticeDimension.user_id == user.id).all()
    practice_dimensions = [
        {"label": item.label, "confidence": item.confidence, "evidence": item.evidence}
        for item in practice_rows
    ]
    competency_levels = build_competency_levels(practice_dimensions)
    weak_first = sorted(competency_levels, key=lambda item: item["score_percent"])
    items = []
    for idx, item in enumerate(weak_first):
        key = item["dimension_key"]
        modules = RULE_MODULES.get(key) or []
        if not modules:
            continue
        start_at = 0
        if len(modules) > 1:
            seed = sum(ord(ch) for ch in f"{user.username}:{key}") + int(idx or 0)
            start_at = seed % len(modules)
        ordered_modules = modules[start_at:] + modules[:start_at]
        for module in ordered_modules:
            items.append(
                {
                    "dimension_key": key,
                    "dimension": item["dimension"],
                    "reason": f"Current level is {item['level']} ({item['score_percent']}%). Prioritize this area.",
                    **module,
                }
            )

    acted_rows = (
        db.query(RecommendationAction)
        .filter(
            RecommendationAction.user_id == user.id,
            RecommendationAction.action.in_(list(ADOPTED_RECOMMENDATION_ACTIONS)),
        )
        .all()
    )
    acted_keys = {
        ((row.module_title or "").strip().lower(), (row.module_url or "").strip().lower())
        for row in acted_rows
    }
    for item in items:
        key = ((item.get("module_title") or "").strip().lower(), (item.get("module_url") or "").strip().lower())
        item["acted"] = key in acted_keys

    shown_cutoff = dt.datetime.utcnow() - dt.timedelta(hours=24)
    for item in items:
        module_title = (item.get("module_title") or "Learning Module").strip()
        module_url = (item.get("module_url") or "").strip()
        already_logged = (
            db.query(RecommendationAction)
            .filter(
                RecommendationAction.user_id == user.id,
                RecommendationAction.action == "shown",
                RecommendationAction.module_title == module_title,
                RecommendationAction.module_url == module_url,
                RecommendationAction.created_at >= shown_cutoff,
            )
            .first()
            is not None
        )
        if already_logged:
            continue
        db.add(
            RecommendationAction(
                user_id=user.id,
                dimension_key=item.get("dimension_key"),
                module_title=module_title,
                module_url=module_url,
                action="shown",
            )
        )
    db.commit()

    from app.services.collaborative_filter import get_peer_recommendations

    peer_recommendations = get_peer_recommendations(db, username)

    return {
        "username": user.username,
        "items": items,
        "peer_recommendations": peer_recommendations,
    }


@router.get("/digest/weekly/{username}", response_model=WeeklyDigestOut)
def get_weekly_digest(username: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return _build_weekly_digest(db, user)


@router.post("/certificates/submit", response_model=CertificateOut)
def submit_certificate(
    payload: CertificateSubmitIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    suggestion_track_id = _normalize_suggestion_track_id(payload.suggestion_track_id)
    suggestion_module_url = _normalize_suggestion_module_url(payload.suggestion_module_url)
    locked_existing = _find_locked_certificate_for_track(db, current_user.id, suggestion_track_id, suggestion_module_url)
    if locked_existing:
        raise HTTPException(status_code=400, detail="This suggested credential is already completed and locked")

    reward_xp = max(0, int(payload.reward_xp or 0))
    row = CertificateRecord(
        user_id=current_user.id,
        title=payload.title.strip(),
        provider=payload.provider.strip(),
        proof_type=(payload.proof_type or "").strip() or None,
        certificate_url=payload.certificate_url.strip(),
        certificate_page_url=(payload.certificate_page_url or "").strip() or None,
        student_note=(payload.student_note or "").strip() or None,
        suggestion_track_id=suggestion_track_id,
        suggestion_module_url=suggestion_module_url,
        completion_locked=bool(payload.final_completion),
        completion_reward_xp=reward_xp if payload.final_completion and reward_xp > 0 else None,
        rewarded_at=None,
        status="pending",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    db.add(ActivityLog(user_id=current_user.id, event="certificate_submit", meta={"certificate_id": row.id}))
    if payload.final_completion:
        db.add(
            ActivityLog(
                user_id=current_user.id,
                event="suggested_certificate_completed",
                meta={
                    "certificate_id": row.id,
                    "suggestion_track_id": suggestion_track_id,
                    "suggestion_module_url": suggestion_module_url,
                    "reward_xp": reward_xp,
                },
            )
        )
    db.commit()
    return _certificate_payload(row, current_user.username)


@router.post("/certificates/claim-reward", response_model=CertificateOut)
def claim_certificate_reward(
    payload: CertificateRewardClaimIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    certificate_id = int(payload.certificate_id or 0)
    if certificate_id <= 0:
        raise HTTPException(status_code=400, detail="certificate_id is required")

    row = (
        db.query(CertificateRecord)
        .filter(CertificateRecord.id == certificate_id, CertificateRecord.user_id == current_user.id)
        .one_or_none()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Certificate not found")
    if not bool(getattr(row, "completion_locked", False)):
        raise HTTPException(status_code=400, detail="This certificate is not ready for reward claiming")

    reward_xp = max(0, int(getattr(row, "completion_reward_xp", 0) or 0))
    if reward_xp <= 0:
        raise HTTPException(status_code=400, detail="No XP reward is available for this certificate")
    if getattr(row, "rewarded_at", None):
        raise HTTPException(status_code=400, detail="This certificate reward was already claimed")

    row.rewarded_at = dt.datetime.utcnow()
    db.add(row)
    db.commit()
    db.refresh(row)

    _add_bonus_xp(
        db,
        current_user,
        reward_xp,
        f"suggested_certificate_complete:{row.suggestion_track_id or row.title}:{row.suggestion_module_url or row.provider}",
    )
    db.add(
        ActivityLog(
            user_id=current_user.id,
            event="suggested_certificate_reward_claimed",
            meta={
                "certificate_id": row.id,
                "suggestion_track_id": row.suggestion_track_id,
                "suggestion_module_url": row.suggestion_module_url,
                "reward_xp": reward_xp,
            },
        )
    )
    db.commit()

    thread_map = _certificate_thread_map(db, current_user.id, [row.id])
    return _certificate_payload(row, current_user.username, thread_map.get(row.id))


@router.post("/certificates/auto-stage-proof", response_model=CertificateOut)
def auto_submit_stage_certificate(
    payload: AutoStageCertificateIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    repo_name = (payload.repo_name or "").strip()
    stage_title = (payload.stage_title or "").strip()
    title = (payload.title or "").strip()
    provider = (payload.provider or "").strip()
    certificate_url = (payload.certificate_url or "").strip()
    if not repo_name or not stage_title or not title or not provider or not certificate_url:
        raise HTTPException(status_code=400, detail="Missing required auto-certificate fields")

    note_parts = [
        f"Auto-created from learning path stage proof.",
        f"Repo: {repo_name}",
        f"Stage: {stage_title}",
    ]
    if (payload.student_note or "").strip():
        note_parts.append((payload.student_note or "").strip())
    student_note = " ".join(note_parts).strip()

    existing = (
        db.query(CertificateRecord)
        .filter(
            CertificateRecord.user_id == current_user.id,
            CertificateRecord.title == title,
            CertificateRecord.provider == provider,
            CertificateRecord.student_note == student_note,
        )
        .order_by(CertificateRecord.submitted_at.desc())
        .first()
    )

    if existing:
        existing.proof_type = (payload.proof_type or "").strip() or existing.proof_type
        existing.certificate_url = certificate_url
        existing.certificate_page_url = (payload.certificate_page_url or "").strip() or existing.certificate_page_url
        if existing.status != "verified":
            existing.status = "pending"
        db.add(existing)
        db.commit()
        db.refresh(existing)
        db.add(ActivityLog(user_id=current_user.id, event="certificate_stage_autoupdate", meta={"certificate_id": existing.id}))
        db.commit()
        row = existing
    else:
        row = CertificateRecord(
            user_id=current_user.id,
            title=title,
            provider=provider,
            proof_type=(payload.proof_type or "").strip() or None,
            certificate_url=certificate_url,
            certificate_page_url=(payload.certificate_page_url or "").strip() or None,
            student_note=student_note,
            status="pending",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        db.add(ActivityLog(user_id=current_user.id, event="certificate_stage_autocreate", meta={"certificate_id": row.id}))
        db.commit()

    return _certificate_payload(row, current_user.username)


@router.post("/certificates/upload")
def upload_certificate(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    raise HTTPException(
        status_code=410,
        detail="Direct file uploads are disabled. Submit a shareable proof URL instead.",
    )


@router.get("/certificates/me", response_model=list[CertificateOut])
def list_my_certificates(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = (
        db.query(CertificateRecord)
        .filter(
            CertificateRecord.user_id == current_user.id,
            or_(
                CertificateRecord.reviewer_note.is_(None),
                ~CertificateRecord.reviewer_note.ilike("Auto-detected via freeCodeCamp URL%"),
            ),
        )
        .order_by(CertificateRecord.submitted_at.desc())
        .all()
    )
    thread_map = _certificate_thread_map(db, current_user.id, [row.id for row in rows])
    return [_certificate_payload(row, current_user.username, thread_map.get(row.id)) for row in rows]


@router.post("/certificates/comment-reply", response_model=CertificateOut)
def reply_certificate_comment(
    payload: CertificateCommentIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    certificate_id = int(payload.certificate_id or 0)
    comment = str(payload.comment or "").strip()
    if certificate_id <= 0 or not comment:
        raise HTTPException(status_code=400, detail="certificate_id and comment are required")

    row = (
        db.query(CertificateRecord)
        .filter(CertificateRecord.id == certificate_id, CertificateRecord.user_id == current_user.id)
        .one_or_none()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Certificate not found")

    db.add(
        ActivityLog(
            user_id=current_user.id,
            event="certificate_student_reply",
            meta={
                "certificate_id": row.id,
                "comment": comment,
                "by": current_user.username,
                "role": "student",
            },
        )
    )
    db.commit()
    thread_map = _certificate_thread_map(db, current_user.id, [row.id])
    return _certificate_payload(row, current_user.username, thread_map.get(row.id))


@router.post("/certificates/comment-reply/delete", response_model=CertificateOut)
def delete_my_certificate_comment_reply(
    payload: CertificateStudentCommentDeleteIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    certificate_id = int(payload.certificate_id or 0)
    updated_at = str(payload.updated_at or "").strip()
    delete_all = bool(payload.delete_all)
    if certificate_id <= 0:
        raise HTTPException(status_code=400, detail="certificate_id is required")
    if not delete_all and not updated_at:
        raise HTTPException(status_code=400, detail="updated_at is required when delete_all is false")

    row = (
        db.query(CertificateRecord)
        .filter(CertificateRecord.id == certificate_id, CertificateRecord.user_id == current_user.id)
        .one_or_none()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Certificate not found")

    matching_logs = (
        db.query(ActivityLog)
        .filter(
            ActivityLog.user_id == current_user.id,
            ActivityLog.event == "certificate_student_reply",
        )
        .order_by(ActivityLog.created_at.asc(), ActivityLog.id.asc())
        .all()
    )
    target_logs: list[ActivityLog] = []
    for log in matching_logs:
        meta = log.meta or {}
        if int(meta.get("certificate_id") or 0) != certificate_id:
            continue
        if str(meta.get("role") or "").strip().lower() != "student":
            continue
        if str(meta.get("by") or "").strip() != current_user.username:
            continue
        if not delete_all and str(log.created_at or "").strip() != updated_at:
            continue
        target_logs.append(log)

    if not target_logs:
        raise HTTPException(status_code=404, detail="Student reply was not found")

    for log in target_logs:
        db.delete(log)
    db.commit()
    thread_map = _certificate_thread_map(db, current_user.id, [row.id])
    return _certificate_payload(row, current_user.username, thread_map.get(row.id))


@router.post("/certificates/progress-delete", response_model=CertificateOut | dict)
def delete_certificate_progress(
    payload: CertificateProgressDeleteIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    certificate_id = int(payload.certificate_id or 0)
    if certificate_id <= 0:
        raise HTTPException(status_code=400, detail="certificate_id is required")
    if not payload.clear_comment and not payload.delete_proof:
        raise HTTPException(status_code=400, detail="No certificate progress change requested")

    row = (
        db.query(CertificateRecord)
        .filter(CertificateRecord.id == certificate_id, CertificateRecord.user_id == current_user.id)
        .one_or_none()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Certificate not found")

    if payload.clear_comment:
        row.student_note = None

    if payload.delete_proof:
        if str(row.status or "").strip().lower() == "verified":
            raise HTTPException(status_code=400, detail="Verified certificate proof cannot be deleted")
        if getattr(row, "rewarded_at", None):
            row.hidden_from_student = True
            db.add(row)
            db.commit()
            db.refresh(row)
            thread_map = _certificate_thread_map(db, current_user.id, [row.id])
            return _certificate_payload(row, current_user.username, thread_map.get(row.id))
        db.delete(row)
        db.commit()
        return {"deleted": True, "certificate_id": certificate_id}

    db.add(row)
    db.commit()
    db.refresh(row)
    thread_map = _certificate_thread_map(db, current_user.id, [row.id])
    return _certificate_payload(row, current_user.username, thread_map.get(row.id))


@router.get("/certificates/fcc-progress", response_model=FccModuleProgressListOut)
def list_my_fcc_module_progress(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = (
        db.query(FccModuleProgress)
        .filter(FccModuleProgress.user_id == current_user.id)
        .order_by(FccModuleProgress.module_title.asc(), FccModuleProgress.id.asc())
        .all()
    )
    return {
        "summary": _fcc_progress_summary(rows),
        "items": [_fcc_progress_payload(row) for row in rows],
    }


@router.put("/learning-path/projects/stage-status", response_model=ProjectStageStatusOut)
def update_project_stage_status(
    payload: ProjectStageStatusIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    repo_name = str(payload.repo_name or "").strip()
    stage_title = str(payload.stage_title or "").strip()
    status = _normalize_project_stage_status(payload.status)
    if not repo_name or not stage_title:
        raise HTTPException(status_code=400, detail="repo_name and stage_title are required")

    portfolio_settings = (
        db.query(PortfolioSettings)
        .filter(PortfolioSettings.user_id == current_user.id)
        .one_or_none()
    )
    if not portfolio_settings:
        portfolio_settings = PortfolioSettings(user_id=current_user.id, learning_path_baseline=[], project_learning_path_baseline={})
        db.add(portfolio_settings)
        db.flush()

    project_baseline = dict(portfolio_settings.project_learning_path_baseline or {})
    baseline_key = _project_baseline_key(project_baseline, repo_name)
    project_entry = project_baseline.get(baseline_key)
    if not isinstance(project_entry, dict):
        project_entry = {
            "baseline_signals": [],
            "latest_signals": [],
            "steps": [],
        }

    def _has_saved_progress_proof(stage_update: object) -> bool:
        if not isinstance(stage_update, dict):
            return False
        raw_entries = stage_update.get("progress_entries")
        if isinstance(raw_entries, list):
            for entry in raw_entries:
                if not isinstance(entry, dict):
                    continue
                proof_items = entry.get("proof_items")
                if isinstance(proof_items, list) and any(
                    isinstance(item, dict) and str(item.get("url") or "").strip()
                    for item in proof_items
                ):
                    return True
        legacy_items = stage_update.get("proof_items")
        return isinstance(legacy_items, list) and any(
            isinstance(item, dict) and str(item.get("url") or "").strip()
            for item in legacy_items
        )

    existing_stage_checks = project_entry.get("stage_checks")
    existing_checks = []
    if isinstance(existing_stage_checks, dict):
        raw_existing_checks = existing_stage_checks.get(stage_title)
        if isinstance(raw_existing_checks, list):
            existing_checks = [bool(item) for item in raw_existing_checks]

    stage_updates = project_entry.get("stage_progress_updates")
    existing_stage_update = stage_updates.get(stage_title) if isinstance(stage_updates, dict) else None
    stage_has_progress_proof = _has_saved_progress_proof(existing_stage_update)

    overrides = project_entry.get("stage_status_overrides")
    if not isinstance(overrides, dict):
        overrides = {}
    overrides[stage_title] = status
    project_entry["stage_status_overrides"] = overrides

    saved_checks = None
    if payload.checks is not None:
        saved_checks = [bool(item) for item in payload.checks]
        if stage_has_progress_proof and any(
            (existing_checks[index] if index < len(existing_checks) else False)
            and not (saved_checks[index] if index < len(saved_checks) else False)
            for index in range(max(len(existing_checks), len(saved_checks)))
        ):
            raise HTTPException(
                status_code=400,
                detail="Delete the saved progress proof for this stage before unchecking its completed outputs",
            )
        stage_checks = project_entry.get("stage_checks")
        if not isinstance(stage_checks, dict):
            stage_checks = {}
        stage_checks[stage_title] = saved_checks
        project_entry["stage_checks"] = stage_checks

    saved_proof_count = None
    if payload.proof_count is not None:
        saved_proof_count = max(0, int(payload.proof_count or 0))
        proof_counts = project_entry.get("stage_proof_counts")
        if not isinstance(proof_counts, dict):
            proof_counts = {}
        proof_counts[stage_title] = saved_proof_count
        project_entry["stage_proof_counts"] = proof_counts

    project_baseline[baseline_key] = project_entry
    portfolio_settings.project_learning_path_baseline = {**project_baseline}
    flag_modified(portfolio_settings, "project_learning_path_baseline")
    db.commit()
    return {
        "repo_name": repo_name,
        "stage_title": stage_title,
        "status": status,
        "checks": saved_checks,
        "proof_count": saved_proof_count,
    }


@router.put("/learning-path/projects/stage-progress-update", response_model=ProjectStageProgressUpdateOut)
def update_project_stage_progress_update(
    payload: ProjectStageProgressUpdateIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    repo_name = str(payload.repo_name or "").strip()
    stage_title = str(payload.stage_title or "").strip()
    comment = str(payload.comment or "").strip() or None
    if not repo_name or not stage_title:
        raise HTTPException(status_code=400, detail="repo_name and stage_title are required")

    def _clean_proof_items(items: list[dict], fallback_name: str) -> list[dict]:
        cleaned: list[dict] = []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            cleaned.append(
                {
                    "name": str(item.get("name") or fallback_name).strip() or fallback_name,
                    "url": url,
                    "kind": str(item.get("kind") or "file").strip().lower() or "file",
                }
            )
        return cleaned

    def _merge_proof_items(existing_items: object, cleaned_items: list[dict], fallback_name: str) -> list[dict]:
        merged: list[dict] = []
        seen_item_urls: set[str] = set()
        existing_list = existing_items if isinstance(existing_items, list) else []
        for item in [*existing_list, *cleaned_items]:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url or url in seen_item_urls:
                continue
            seen_item_urls.add(url)
            merged.append(
                {
                    "name": str(item.get("name") or fallback_name).strip() or fallback_name,
                    "url": url,
                    "kind": str(item.get("kind") or "file").strip().lower() or "file",
                }
            )
        return merged

    def _normalize_progress_entries(existing_update: dict | None) -> list[dict]:
        if not isinstance(existing_update, dict):
            return []
        normalized: list[dict] = []
        raw_entries = existing_update.get("progress_entries")
        if isinstance(raw_entries, list):
            for index, entry in enumerate(raw_entries):
                if not isinstance(entry, dict):
                    continue
                entry_id = str(entry.get("entry_id") or "").strip() or f"legacy-{index + 1}"
                normalized.append(
                    {
                        "entry_id": entry_id,
                        "comment": entry.get("comment"),
                        "proof_items": _clean_proof_items(entry.get("proof_items") if isinstance(entry.get("proof_items"), list) else [], "Progress proof"),
                        "updated_at": entry.get("updated_at"),
                    }
                )
        if normalized:
            return normalized
        legacy_comment = existing_update.get("comment")
        legacy_items = _clean_proof_items(existing_update.get("proof_items") if isinstance(existing_update.get("proof_items"), list) else [], "Progress proof")
        legacy_updated_at = existing_update.get("updated_at")
        if legacy_comment or legacy_items:
            return [
                {
                    "entry_id": f"legacy-{int(time.time() * 1000)}",
                    "comment": legacy_comment,
                    "proof_items": legacy_items,
                    "updated_at": legacy_updated_at,
                }
            ]
        return []

    cleaned_items = _clean_proof_items(payload.proof_items or [], "Progress proof")
    cleaned_final_items = _clean_proof_items(payload.final_proof_items or [], "Final stage proof")

    portfolio_settings = (
        db.query(PortfolioSettings)
        .filter(PortfolioSettings.user_id == current_user.id)
        .one_or_none()
    )
    if not portfolio_settings:
        portfolio_settings = PortfolioSettings(user_id=current_user.id, learning_path_baseline=[], project_learning_path_baseline={})
        db.add(portfolio_settings)
        db.flush()

    project_baseline = dict(portfolio_settings.project_learning_path_baseline or {})
    baseline_key = _project_baseline_key(project_baseline, repo_name)
    project_entry = project_baseline.get(baseline_key)
    if not isinstance(project_entry, dict):
        project_entry = {
            "baseline_signals": [],
            "latest_signals": [],
            "steps": [],
        }

    stage_updates = project_entry.get("stage_progress_updates")
    if not isinstance(stage_updates, dict):
        stage_updates = {}

    existing_update = stage_updates.get(stage_title)
    existing_items = existing_update.get("proof_items") if isinstance(existing_update, dict) else []
    existing_final_items = existing_update.get("final_proof_items") if isinstance(existing_update, dict) else []
    existing_comment = existing_update.get("comment") if isinstance(existing_update, dict) else None
    progress_entries = _normalize_progress_entries(existing_update if isinstance(existing_update, dict) else None)
    next_comment = comment if comment is not None else existing_comment
    merged_items = _merge_proof_items(existing_items, cleaned_items, "Progress proof")
    merged_final_items = _merge_proof_items(existing_final_items, cleaned_final_items, "Final stage proof")

    proof_counts = project_entry.get("stage_proof_counts")
    if not isinstance(proof_counts, dict):
        proof_counts = {}

    updated_at = dt.datetime.now(dt.timezone.utc).isoformat()
    if cleaned_items or comment is not None:
        progress_entries.append(
            {
                "entry_id": f"{int(time.time() * 1000)}-{len(progress_entries) + 1}",
                "comment": comment,
                "proof_items": cleaned_items,
                "updated_at": updated_at,
            }
        )
        next_comment = comment
        merged_items = cleaned_items
    stage_updates[stage_title] = {
        **(existing_update if isinstance(existing_update, dict) else {}),
        "comment": next_comment,
        "proof_items": merged_items,
        "final_proof_items": merged_final_items,
        "progress_entries": progress_entries,
        "updated_at": updated_at,
    }
    if cleaned_final_items:
        stage_updates[stage_title]["review_status"] = "pending"
        stage_updates[stage_title]["review_status_updated_at"] = updated_at
    saved_progress_proof_count = sum(
        len(entry.get("proof_items") if isinstance(entry.get("proof_items"), list) else [])
        for entry in progress_entries
        if isinstance(entry, dict)
    )
    if saved_progress_proof_count > 0:
        proof_counts[stage_title] = saved_progress_proof_count
    else:
        proof_counts.pop(stage_title, None)
    project_entry["stage_progress_updates"] = stage_updates
    project_entry["stage_proof_counts"] = proof_counts
    project_baseline[baseline_key] = project_entry
    portfolio_settings.project_learning_path_baseline = {**project_baseline}
    flag_modified(portfolio_settings, "project_learning_path_baseline")
    db.add(ActivityLog(user_id=current_user.id, event="project_stage_progress_update", meta={"repo_name": repo_name, "stage_title": stage_title}))
    db.commit()
    return {
        "repo_name": repo_name,
        "stage_title": stage_title,
        "comment": next_comment,
        "proof_items": merged_items,
        "final_proof_items": merged_final_items,
        "review_status": stage_updates[stage_title].get("review_status"),
        "review_status_updated_at": stage_updates[stage_title].get("review_status_updated_at"),
        "updated_at": updated_at,
        "progress_entries": progress_entries,
        "admin_feedback": stage_updates[stage_title].get("admin_feedback"),
        "admin_feedback_by": stage_updates[stage_title].get("admin_feedback_by"),
        "admin_feedback_updated_at": stage_updates[stage_title].get("admin_feedback_updated_at"),
        "admin_feedback_thread": stage_updates[stage_title].get("admin_feedback_thread") if isinstance(stage_updates[stage_title].get("admin_feedback_thread"), list) else [],
        "admin_feedback_by_proof": stage_updates[stage_title].get("admin_feedback_by_proof") if isinstance(stage_updates[stage_title].get("admin_feedback_by_proof"), dict) else {},
    }


@router.post("/learning-path/projects/stage-feedback-reply", response_model=ProjectStageProgressUpdateOut)
def reply_project_stage_feedback(
    payload: ProjectStageFeedbackReplyIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    repo_name = str(payload.repo_name or "").strip()
    stage_title = str(payload.stage_title or "").strip()
    feedback = str(payload.feedback or "").strip()
    proof_url = str(payload.proof_url or "").strip()
    proof_name = str(payload.proof_name or "").strip()
    if not repo_name or not stage_title:
        raise HTTPException(status_code=400, detail="repo_name and stage_title are required")
    if not feedback:
        raise HTTPException(status_code=400, detail="Feedback is required")

    portfolio_settings = (
        db.query(PortfolioSettings)
        .filter(PortfolioSettings.user_id == current_user.id)
        .one_or_none()
    )
    if not portfolio_settings:
        raise HTTPException(status_code=404, detail="Learning path stage was not found")

    project_baseline = dict(portfolio_settings.project_learning_path_baseline or {})
    baseline_key = _project_baseline_key(project_baseline, repo_name)
    project_entry = project_baseline.get(baseline_key)
    if not isinstance(project_entry, dict):
        project_entry = {"baseline_signals": [], "latest_signals": [], "steps": []}

    stage_updates = project_entry.get("stage_progress_updates")
    if not isinstance(stage_updates, dict):
        stage_updates = {}
    stage_update = stage_updates.get(stage_title)
    if not isinstance(stage_update, dict):
        stage_update = {
            "comment": None,
            "proof_items": [],
            "final_proof_items": [],
            "progress_entries": [],
        }

    updated_at = dt.datetime.now(dt.timezone.utc).isoformat()
    if proof_url:
        feedback_by_proof = stage_update.get("admin_feedback_by_proof")
        if not isinstance(feedback_by_proof, dict):
            feedback_by_proof = {}
        proof_feedback = feedback_by_proof.get(proof_url)
        if not isinstance(proof_feedback, dict):
            proof_feedback = {"proof_url": proof_url, "proof_name": proof_name, "thread": []}
        thread = proof_feedback.get("thread")
        if not isinstance(thread, list):
            thread = []
        thread.append(
            {
                "feedback": feedback,
                "by": current_user.username,
                "role": "student",
                "updated_at": updated_at,
                "proof_url": proof_url,
                "proof_name": proof_name,
            }
        )
        proof_feedback["proof_url"] = proof_url
        proof_feedback["proof_name"] = proof_name
        proof_feedback["thread"] = thread
        proof_feedback["latest_feedback"] = feedback
        proof_feedback["feedback_by"] = current_user.username
        proof_feedback["updated_at"] = updated_at
        feedback_by_proof[proof_url] = proof_feedback
        stage_update["admin_feedback_by_proof"] = feedback_by_proof
    else:
        feedback_thread = stage_update.get("admin_feedback_thread")
        if not isinstance(feedback_thread, list):
            feedback_thread = []
        feedback_thread.append(
            {
                "feedback": feedback,
                "by": current_user.username,
                "role": "student",
                "updated_at": updated_at,
            }
        )
        stage_update["admin_feedback_thread"] = feedback_thread

    stage_update["updated_at"] = updated_at
    stage_updates[stage_title] = stage_update
    project_entry["stage_progress_updates"] = stage_updates
    project_baseline[baseline_key] = project_entry
    portfolio_settings.project_learning_path_baseline = {**project_baseline}
    flag_modified(portfolio_settings, "project_learning_path_baseline")
    db.add(ActivityLog(user_id=current_user.id, event="project_stage_feedback_reply", meta={"repo_name": repo_name, "stage_title": stage_title, "proof_url": proof_url or None, "proof_name": proof_name or None}))
    db.commit()
    return {
        "repo_name": repo_name,
        "stage_title": stage_title,
        "comment": stage_update.get("comment"),
        "proof_items": stage_update.get("proof_items") if isinstance(stage_update.get("proof_items"), list) else [],
        "final_proof_items": stage_update.get("final_proof_items") if isinstance(stage_update.get("final_proof_items"), list) else [],
        "review_status": stage_update.get("review_status"),
        "review_status_updated_at": stage_update.get("review_status_updated_at"),
        "updated_at": updated_at,
        "progress_entries": stage_update.get("progress_entries") if isinstance(stage_update.get("progress_entries"), list) else [],
        "admin_feedback": stage_update.get("admin_feedback"),
        "admin_feedback_by": stage_update.get("admin_feedback_by"),
        "admin_feedback_updated_at": stage_update.get("admin_feedback_updated_at"),
        "admin_feedback_thread": stage_update.get("admin_feedback_thread") if isinstance(stage_update.get("admin_feedback_thread"), list) else [],
        "admin_feedback_by_proof": stage_update.get("admin_feedback_by_proof") if isinstance(stage_update.get("admin_feedback_by_proof"), dict) else {},
    }


@router.post("/learning-path/projects/stage-feedback-reply/delete", response_model=ProjectStageProgressUpdateOut)
def delete_project_stage_feedback_reply(
    payload: ProjectStageFeedbackReplyDeleteIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    repo_name = str(payload.repo_name or "").strip()
    stage_title = str(payload.stage_title or "").strip()
    updated_at = str(payload.updated_at or "").strip()
    proof_url = str(payload.proof_url or "").strip()
    delete_all = bool(payload.delete_all)
    if not repo_name or not stage_title:
        raise HTTPException(status_code=400, detail="repo_name and stage_title are required")
    if not delete_all and not updated_at:
        raise HTTPException(status_code=400, detail="updated_at is required when delete_all is false")

    def _is_current_student_reply(entry: object) -> bool:
        return (
            isinstance(entry, dict)
            and str(entry.get("role") or "").strip().lower() == "student"
            and str(entry.get("by") or "").strip() == current_user.username
        )

    portfolio_settings = (
        db.query(PortfolioSettings)
        .filter(PortfolioSettings.user_id == current_user.id)
        .one_or_none()
    )
    if not portfolio_settings:
        raise HTTPException(status_code=404, detail="Learning path stage was not found")

    project_baseline = dict(portfolio_settings.project_learning_path_baseline or {})
    baseline_key = _project_baseline_key(project_baseline, repo_name)
    project_entry = project_baseline.get(baseline_key)
    if not isinstance(project_entry, dict):
        raise HTTPException(status_code=404, detail="Learning path stage was not found")

    stage_updates = project_entry.get("stage_progress_updates")
    if not isinstance(stage_updates, dict):
        raise HTTPException(status_code=404, detail="Learning path stage was not found")
    stage_update = stage_updates.get(stage_title)
    if not isinstance(stage_update, dict):
        raise HTTPException(status_code=404, detail="Learning path stage was not found")

    updated_thread: list[dict] = []
    if proof_url:
        feedback_by_proof = stage_update.get("admin_feedback_by_proof")
        if not isinstance(feedback_by_proof, dict):
            raise HTTPException(status_code=404, detail="Proof comment thread was not found")
        proof_feedback = feedback_by_proof.get(proof_url)
        if not isinstance(proof_feedback, dict):
            raise HTTPException(status_code=404, detail="Proof comment thread was not found")
        thread = proof_feedback.get("thread")
        if not isinstance(thread, list):
            thread = []
        next_thread = [
            entry for entry in thread
            if not (
                _is_current_student_reply(entry)
                and (delete_all or str(entry.get("updated_at") or "").strip() == updated_at)
            )
        ]
        if len(next_thread) == len(thread):
            raise HTTPException(status_code=404, detail="Student reply was not found")
        if next_thread:
            latest_admin = next(
                (
                    entry for entry in reversed(next_thread)
                    if isinstance(entry, dict) and str(entry.get("role") or "").strip().lower() == "admin"
                ),
                None,
            )
            proof_feedback["thread"] = next_thread
            proof_feedback["latest_feedback"] = latest_admin.get("feedback") if isinstance(latest_admin, dict) else None
            proof_feedback["feedback_by"] = latest_admin.get("by") if isinstance(latest_admin, dict) else None
            proof_feedback["updated_at"] = latest_admin.get("updated_at") if isinstance(latest_admin, dict) else None
            feedback_by_proof[proof_url] = proof_feedback
        else:
            feedback_by_proof.pop(proof_url, None)
        stage_update["admin_feedback_by_proof"] = feedback_by_proof
        updated_thread = next_thread
    else:
        thread = stage_update.get("admin_feedback_thread")
        if not isinstance(thread, list):
            thread = []
        next_thread = [
            entry for entry in thread
            if not (
                _is_current_student_reply(entry)
                and (delete_all or str(entry.get("updated_at") or "").strip() == updated_at)
            )
        ]
        if len(next_thread) == len(thread):
            raise HTTPException(status_code=404, detail="Student reply was not found")
        stage_update["admin_feedback_thread"] = next_thread
        updated_thread = next_thread

    stage_update["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    stage_updates[stage_title] = stage_update
    project_entry["stage_progress_updates"] = stage_updates
    project_baseline[baseline_key] = project_entry
    portfolio_settings.project_learning_path_baseline = {**project_baseline}
    flag_modified(portfolio_settings, "project_learning_path_baseline")
    db.commit()
    return {
        "repo_name": repo_name,
        "stage_title": stage_title,
        "comment": stage_update.get("comment"),
        "proof_items": stage_update.get("proof_items") if isinstance(stage_update.get("proof_items"), list) else [],
        "final_proof_items": stage_update.get("final_proof_items") if isinstance(stage_update.get("final_proof_items"), list) else [],
        "review_status": stage_update.get("review_status"),
        "review_status_updated_at": stage_update.get("review_status_updated_at"),
        "updated_at": stage_update.get("updated_at"),
        "progress_entries": stage_update.get("progress_entries") if isinstance(stage_update.get("progress_entries"), list) else [],
        "admin_feedback": stage_update.get("admin_feedback"),
        "admin_feedback_by": stage_update.get("admin_feedback_by"),
        "admin_feedback_updated_at": stage_update.get("admin_feedback_updated_at"),
        "admin_feedback_thread": updated_thread if not proof_url else (stage_update.get("admin_feedback_thread") if isinstance(stage_update.get("admin_feedback_thread"), list) else []),
        "admin_feedback_by_proof": stage_update.get("admin_feedback_by_proof") if isinstance(stage_update.get("admin_feedback_by_proof"), dict) else {},
    }


@router.post("/learning-path/projects/stage-progress-update/delete", response_model=ProjectStageProgressUpdateOut)
def delete_project_stage_progress_update(
    payload: ProjectStageProgressDeleteIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    repo_name = str(payload.repo_name or "").strip()
    stage_title = str(payload.stage_title or "").strip()
    entry_id = str(payload.entry_id or "").strip()
    proof_url = str(payload.proof_url or "").strip()
    clear_comment = bool(payload.clear_comment)
    delete_entry = bool(payload.delete_entry)
    if not repo_name or not stage_title:
        raise HTTPException(status_code=400, detail="repo_name and stage_title are required")
    if not delete_entry and not clear_comment and not proof_url:
        raise HTTPException(status_code=400, detail="proof_url is required when clear_comment is false")

    portfolio_settings = (
        db.query(PortfolioSettings)
        .filter(PortfolioSettings.user_id == current_user.id)
        .one_or_none()
    )
    if not portfolio_settings:
        raise HTTPException(status_code=404, detail="Learning path progress update was not found")

    project_baseline = dict(portfolio_settings.project_learning_path_baseline or {})
    baseline_key = _project_baseline_key(project_baseline, repo_name)
    project_entry = project_baseline.get(baseline_key)
    if not isinstance(project_entry, dict):
        raise HTTPException(status_code=404, detail="Learning path progress update was not found")

    stage_updates = project_entry.get("stage_progress_updates")
    if not isinstance(stage_updates, dict):
        raise HTTPException(status_code=404, detail="Learning path progress update was not found")

    existing_update = stage_updates.get(stage_title)
    if not isinstance(existing_update, dict):
        raise HTTPException(status_code=404, detail="Learning path progress update was not found")

    raw_progress_entries = existing_update.get("progress_entries")
    progress_entries = raw_progress_entries if isinstance(raw_progress_entries, list) else []
    if not progress_entries:
        legacy_items = existing_update.get("proof_items")
        progress_entries = [{
            "entry_id": entry_id or f"legacy-{int(time.time() * 1000)}",
            "comment": existing_update.get("comment"),
            "proof_items": legacy_items if isinstance(legacy_items, list) else [],
            "updated_at": existing_update.get("updated_at"),
        }]

    target_index = -1
    if entry_id:
        for index, entry in enumerate(progress_entries):
            if isinstance(entry, dict) and str(entry.get("entry_id") or "").strip() == entry_id:
                target_index = index
                break
    elif proof_url:
        for index, entry in enumerate(progress_entries):
            entry_items = entry.get("proof_items") if isinstance(entry, dict) else []
            if any(isinstance(item, dict) and str(item.get("url") or "").strip() == proof_url for item in (entry_items if isinstance(entry_items, list) else [])):
                target_index = index
                break
    elif progress_entries:
        target_index = len(progress_entries) - 1

    if target_index < 0:
        raise HTTPException(status_code=404, detail="Learning path progress update was not found")

    target_entry = progress_entries[target_index] if isinstance(progress_entries[target_index], dict) else {}
    progress_items = target_entry.get("proof_items") if isinstance(target_entry.get("proof_items"), list) else []
    next_items = progress_items
    if delete_entry:
        progress_entries = [entry for index, entry in enumerate(progress_entries) if index != target_index]
        entry_proof_urls = [
            str(item.get("url") or "").strip()
            for item in progress_items
            if isinstance(item, dict) and str(item.get("url") or "").strip()
        ]
        feedback_by_proof = existing_update.get("admin_feedback_by_proof")
        if isinstance(feedback_by_proof, dict):
            feedback_by_proof = {**feedback_by_proof}
            for entry_proof_url in entry_proof_urls:
                feedback_by_proof.pop(entry_proof_url, None)
            existing_update["admin_feedback_by_proof"] = feedback_by_proof
    elif proof_url:
        next_items = [
            item for item in progress_items
            if not (isinstance(item, dict) and str(item.get("url") or "").strip() == proof_url)
        ]
        if len(next_items) == len(progress_items):
            raise HTTPException(status_code=404, detail="Learning path progress proof was not found")
        feedback_by_proof = existing_update.get("admin_feedback_by_proof")
        if isinstance(feedback_by_proof, dict):
            feedback_by_proof = {**feedback_by_proof}
            feedback_by_proof.pop(proof_url, None)
            existing_update["admin_feedback_by_proof"] = feedback_by_proof

    next_comment = None if clear_comment else target_entry.get("comment")
    if not delete_entry and not clear_comment and next_items == progress_items:
        raise HTTPException(status_code=400, detail="No progress update changes were requested")

    updated_at = dt.datetime.now(dt.timezone.utc).isoformat()
    if not delete_entry:
        updated_entry = {
            **target_entry,
            "comment": next_comment,
            "proof_items": next_items,
            "updated_at": updated_at,
        }
        if not updated_entry.get("comment") and not updated_entry.get("proof_items"):
            progress_entries = [entry for index, entry in enumerate(progress_entries) if index != target_index]
        else:
            progress_entries[target_index] = updated_entry

    latest_entry = next((entry for entry in reversed(progress_entries) if isinstance(entry, dict)), {})
    stage_updates[stage_title] = {
        **existing_update,
        "comment": latest_entry.get("comment"),
        "proof_items": latest_entry.get("proof_items") if isinstance(latest_entry.get("proof_items"), list) else [],
        "final_proof_items": existing_update.get("final_proof_items") if isinstance(existing_update.get("final_proof_items"), list) else [],
        "progress_entries": progress_entries,
        "updated_at": updated_at,
    }

    proof_counts = project_entry.get("stage_proof_counts")
    if not isinstance(proof_counts, dict):
        proof_counts = {}
    saved_progress_proof_count = sum(
        len(entry.get("proof_items") if isinstance(entry.get("proof_items"), list) else [])
        for entry in progress_entries
        if isinstance(entry, dict)
    )
    if saved_progress_proof_count > 0:
        proof_counts[stage_title] = saved_progress_proof_count
    else:
        proof_counts.pop(stage_title, None)

    project_entry["stage_progress_updates"] = stage_updates
    project_entry["stage_proof_counts"] = proof_counts
    project_baseline[baseline_key] = project_entry
    portfolio_settings.project_learning_path_baseline = {**project_baseline}
    flag_modified(portfolio_settings, "project_learning_path_baseline")
    db.add(
        ActivityLog(
            user_id=current_user.id,
            event="project_stage_progress_update_delete",
            meta={"repo_name": repo_name, "stage_title": stage_title, "proof_url": proof_url or None, "clear_comment": clear_comment, "delete_entry": delete_entry},
        )
    )
    db.commit()
    return {
        "repo_name": repo_name,
        "stage_title": stage_title,
        "comment": stage_updates[stage_title].get("comment"),
        "proof_items": stage_updates[stage_title].get("proof_items") if isinstance(stage_updates[stage_title].get("proof_items"), list) else [],
        "final_proof_items": stage_updates[stage_title].get("final_proof_items") if isinstance(stage_updates[stage_title].get("final_proof_items"), list) else [],
        "review_status": stage_updates[stage_title].get("review_status"),
        "review_status_updated_at": stage_updates[stage_title].get("review_status_updated_at"),
        "updated_at": updated_at,
        "progress_entries": stage_updates[stage_title].get("progress_entries") if isinstance(stage_updates[stage_title].get("progress_entries"), list) else [],
        "admin_feedback": stage_updates[stage_title].get("admin_feedback"),
        "admin_feedback_by": stage_updates[stage_title].get("admin_feedback_by"),
        "admin_feedback_updated_at": stage_updates[stage_title].get("admin_feedback_updated_at"),
        "admin_feedback_thread": stage_updates[stage_title].get("admin_feedback_thread") if isinstance(stage_updates[stage_title].get("admin_feedback_thread"), list) else [],
        "admin_feedback_by_proof": stage_updates[stage_title].get("admin_feedback_by_proof") if isinstance(stage_updates[stage_title].get("admin_feedback_by_proof"), dict) else {},
    }


@router.delete("/learning-path/projects/stage-proof", response_model=ProjectStageProgressUpdateOut)
def delete_project_stage_proof(
    payload: ProjectStageProofDeleteIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    repo_name = str(payload.repo_name or "").strip()
    stage_title = str(payload.stage_title or "").strip()
    proof_url = str(payload.proof_url or "").strip()
    if not repo_name or not stage_title or not proof_url:
        raise HTTPException(status_code=400, detail="repo_name, stage_title, and proof_url are required")

    portfolio_settings = (
        db.query(PortfolioSettings)
        .filter(PortfolioSettings.user_id == current_user.id)
        .one_or_none()
    )
    if not portfolio_settings:
        raise HTTPException(status_code=404, detail="Learning path proof was not found")

    project_baseline = dict(portfolio_settings.project_learning_path_baseline or {})
    baseline_key = _project_baseline_key(project_baseline, repo_name)
    project_entry = project_baseline.get(baseline_key)
    if not isinstance(project_entry, dict):
        raise HTTPException(status_code=404, detail="Learning path proof was not found")

    stage_updates = project_entry.get("stage_progress_updates")
    if not isinstance(stage_updates, dict):
        raise HTTPException(status_code=404, detail="Learning path proof was not found")

    existing_update = stage_updates.get(stage_title)
    if not isinstance(existing_update, dict):
        raise HTTPException(status_code=404, detail="Learning path proof was not found")

    existing_items = existing_update.get("final_proof_items")
    delete_from_legacy_progress_items = False
    if not isinstance(existing_items, list) or not existing_items:
        legacy_items = existing_update.get("proof_items")
        existing_items = legacy_items if isinstance(legacy_items, list) else []
        delete_from_legacy_progress_items = True

    next_items = [
        item for item in existing_items
        if isinstance(item, dict) and str(item.get("url") or "").strip() != proof_url
    ]
    if len(next_items) == len(existing_items):
        raise HTTPException(status_code=404, detail="Learning path proof was not found")

    feedback_by_proof = existing_update.get("admin_feedback_by_proof")
    if isinstance(feedback_by_proof, dict):
        feedback_by_proof = {**feedback_by_proof}
        feedback_by_proof.pop(proof_url, None)
        existing_update["admin_feedback_by_proof"] = feedback_by_proof

    updated_at = dt.datetime.now(dt.timezone.utc).isoformat()
    stage_updates[stage_title] = {
        **existing_update,
        ("proof_items" if delete_from_legacy_progress_items else "final_proof_items"): next_items,
        "updated_at": updated_at,
    }

    proof_counts = project_entry.get("stage_proof_counts")
    if not isinstance(proof_counts, dict):
        proof_counts = {}
    if next_items:
        proof_counts[stage_title] = len(next_items)
    else:
        proof_counts.pop(stage_title, None)

    project_entry["stage_progress_updates"] = stage_updates
    project_entry["stage_proof_counts"] = proof_counts
    project_baseline[baseline_key] = project_entry
    portfolio_settings.project_learning_path_baseline = {**project_baseline}
    flag_modified(portfolio_settings, "project_learning_path_baseline")
    db.add(ActivityLog(user_id=current_user.id, event="project_stage_proof_delete", meta={"repo_name": repo_name, "stage_title": stage_title}))
    db.commit()
    return {
        "repo_name": repo_name,
        "stage_title": stage_title,
        "comment": stage_updates[stage_title].get("comment"),
        "proof_items": stage_updates[stage_title].get("proof_items") if isinstance(stage_updates[stage_title].get("proof_items"), list) else [],
        "final_proof_items": stage_updates[stage_title].get("final_proof_items") if isinstance(stage_updates[stage_title].get("final_proof_items"), list) else [],
        "review_status": stage_updates[stage_title].get("review_status"),
        "review_status_updated_at": stage_updates[stage_title].get("review_status_updated_at"),
        "updated_at": updated_at,
        "progress_entries": stage_updates[stage_title].get("progress_entries") if isinstance(stage_updates[stage_title].get("progress_entries"), list) else [],
        "admin_feedback": stage_updates[stage_title].get("admin_feedback"),
        "admin_feedback_by": stage_updates[stage_title].get("admin_feedback_by"),
        "admin_feedback_updated_at": stage_updates[stage_title].get("admin_feedback_updated_at"),
        "admin_feedback_thread": stage_updates[stage_title].get("admin_feedback_thread") if isinstance(stage_updates[stage_title].get("admin_feedback_thread"), list) else [],
        "admin_feedback_by_proof": stage_updates[stage_title].get("admin_feedback_by_proof") if isinstance(stage_updates[stage_title].get("admin_feedback_by_proof"), dict) else {},
    }


@router.put("/certificates/fcc-progress/{module_key}", response_model=FccModuleProgressOut)
def upsert_my_fcc_module_progress(
    module_key: str,
    payload: FccModuleProgressIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    clean_key = (module_key or "").strip().lower()
    if not clean_key:
        raise HTTPException(status_code=400, detail="Module key is required")

    module_title = (payload.module_title or "").strip()
    if not module_title:
        raise HTTPException(status_code=400, detail="Module title is required")

    progress_percent = max(0, min(100, int(payload.progress_percent or 0)))
    status = _normalize_fcc_status(payload.status, progress_percent)
    notes = (payload.notes or "").strip() or None
    certificate_url = (payload.certificate_url or "").strip() or None

    row = (
        db.query(FccModuleProgress)
        .filter(FccModuleProgress.user_id == current_user.id, FccModuleProgress.module_key == clean_key)
        .one_or_none()
    )
    if not row:
        row = FccModuleProgress(
            user_id=current_user.id,
            module_key=clean_key,
            module_title=module_title,
        )
        db.add(row)

    row.module_title = module_title
    row.progress_percent = progress_percent
    row.status = status
    row.notes = notes
    row.certificate_url = certificate_url
    row.completed_at = dt.datetime.utcnow() if status == "done" or progress_percent >= 100 else None

    db.add(ActivityLog(user_id=current_user.id, event="fcc_progress_update", meta={"module_key": clean_key, "status": status, "progress_percent": progress_percent}))
    db.commit()
    db.refresh(row)
    return _fcc_progress_payload(row)


@router.get("/learning-accounts", response_model=LearningAccountsOut)
def get_learning_accounts(
    current_user: User = Depends(get_current_user),
):
    return {
        "username": current_user.username,
        "freecodecamp_username": current_user.freecodecamp_username,
        "last_cert_sync_at": current_user.last_cert_sync_at.isoformat() if current_user.last_cert_sync_at else None,
    }


@router.put("/learning-accounts", response_model=LearningAccountsOut)
def update_learning_accounts(
    payload: LearningAccountsIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    current_user.freecodecamp_username = (payload.freecodecamp_username or "").strip() or None
    db.add(current_user)
    db.add(ActivityLog(user_id=current_user.id, event="learning_accounts_update"))
    db.commit()
    db.refresh(current_user)
    return {
        "username": current_user.username,
        "freecodecamp_username": current_user.freecodecamp_username,
        "last_cert_sync_at": current_user.last_cert_sync_at.isoformat() if current_user.last_cert_sync_at else None,
    }


@router.get("/learning-accounts/freecodecamp/stats", response_model=LearningAccountStatsOut)
def get_my_freecodecamp_stats(
    refresh_public: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return get_freecodecamp_stats(db, current_user, refresh_public=refresh_public)


@router.post("/learning-accounts/freecodecamp/sync", response_model=AutoSyncResultOut)
def sync_my_freecodecamp_certificates(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = sync_freecodecamp_certificates(db, current_user)
    _mark_synced_fcc_certificates_as_done(db, current_user, result)
    return result


def _goal_payload(row: StudentGoal) -> dict:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "title": row.title,
        "target_value": row.target_value,
        "current_value": int(row.current_value or 0),
        "unit": row.unit,
        "status": row.status,
        "target_date": row.target_date,
        "notes": row.notes,
        "created_at": str(row.created_at),
        "updated_at": str(row.updated_at) if row.updated_at else None,
    }


@router.get("/goals/me", response_model=list[StudentGoalOut])
def list_my_goals(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = (
        db.query(StudentGoal)
        .filter(StudentGoal.user_id == current_user.id)
        .order_by(StudentGoal.created_at.desc())
        .all()
    )
    return [_goal_payload(row) for row in rows]


@router.post("/goals/me", response_model=StudentGoalOut)
def create_my_goal(
    payload: StudentGoalIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    title = (payload.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Goal title is required")
    if len(title) > 255:
        raise HTTPException(status_code=400, detail="Goal title is too long")
    status = (payload.status or "active").strip().lower()
    if status not in {"active", "completed", "paused"}:
        raise HTTPException(status_code=400, detail="Invalid goal status")

    row = StudentGoal(
        user_id=current_user.id,
        title=title,
        target_value=payload.target_value,
        current_value=int(payload.current_value or 0),
        unit=(payload.unit or "").strip() or None,
        status=status,
        target_date=(payload.target_date or "").strip() or None,
        notes=(payload.notes or "").strip() or None,
    )
    db.add(row)
    db.add(ActivityLog(user_id=current_user.id, event="goal_create", meta={"title": title}))
    db.commit()
    db.refresh(row)
    return _goal_payload(row)


@router.put("/goals/me/{goal_id}", response_model=StudentGoalOut)
def update_my_goal(
    goal_id: int,
    payload: StudentGoalUpdateIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = (
        db.query(StudentGoal)
        .filter(StudentGoal.id == goal_id, StudentGoal.user_id == current_user.id)
        .one_or_none()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Goal not found")

    if payload.title is not None:
        title = payload.title.strip()
        if not title:
            raise HTTPException(status_code=400, detail="Goal title is required")
        row.title = title[:255]
    if payload.target_value is not None:
        row.target_value = int(payload.target_value)
    if payload.current_value is not None:
        row.current_value = int(payload.current_value)
    if payload.unit is not None:
        row.unit = payload.unit.strip() or None
    if payload.status is not None:
        status = payload.status.strip().lower()
        if status not in {"active", "completed", "paused"}:
            raise HTTPException(status_code=400, detail="Invalid goal status")
        row.status = status
    if payload.target_date is not None:
        row.target_date = payload.target_date.strip() or None
    if payload.notes is not None:
        row.notes = payload.notes.strip() or None

    db.add(row)
    db.add(ActivityLog(user_id=current_user.id, event="goal_update", meta={"goal_id": goal_id}))
    db.commit()
    db.refresh(row)
    return _goal_payload(row)


@router.delete("/goals/me/{goal_id}")
def delete_my_goal(
    goal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = (
        db.query(StudentGoal)
        .filter(StudentGoal.id == goal_id, StudentGoal.user_id == current_user.id)
        .one_or_none()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Goal not found")
    db.delete(row)
    db.add(ActivityLog(user_id=current_user.id, event="goal_delete", meta={"goal_id": goal_id}))
    db.commit()
    return {"ok": True}


@router.get("/validations/me", response_model=list[ProjectValidationOut])
def list_my_project_validations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = (
        db.query(ProjectValidation)
        .filter(ProjectValidation.student_id == current_user.id)
        .order_by(ProjectValidation.created_at.desc())
        .all()
    )
    return [
        ProjectValidationOut(
            id=row.id,
            admin_id=row.admin_id,
            student_id=row.student_id,
            repo_name=row.repo_name,
            status=row.status,
            comment=row.comment,
            created_at=str(row.created_at),
        )
        for row in rows
    ]


@router.post("/recommendations/action")
def track_recommendation_action(
    payload: RecommendationActionIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    action = ((payload.action_type or payload.action) or "").strip().lower()
    if action not in {"shown", "clicked", "accepted", "completed", "started", "rejected", "rated", "not_started", "in_progress"}:
        raise HTTPException(status_code=400, detail="Invalid recommendation action")
    if action == "rated" and payload.rating is None:
        raise HTTPException(status_code=400, detail="Rating is required for rated action")
    module_title = payload.module_title.strip()
    module_url = payload.module_url.strip()
    if not module_title or len(module_title) > 255:
        raise HTTPException(status_code=400, detail="Invalid module title")
    if not module_url or len(module_url) > 2000:
        raise HTTPException(status_code=400, detail="Invalid module url")
    if payload.rating is not None and int(payload.rating) not in {1, 2, 3, 4, 5}:
        raise HTTPException(status_code=400, detail="Rating must be 1-5")

    clean_feedback = (payload.feedback or "").strip() or None
    if clean_feedback and len(clean_feedback) > 1000:
        clean_feedback = clean_feedback[:1000]

    duplicate_cutoff = dt.datetime.utcnow() - dt.timedelta(seconds=30)
    is_duplicate = (
        db.query(RecommendationAction)
        .filter(
            RecommendationAction.user_id == current_user.id,
            RecommendationAction.action == action,
            RecommendationAction.module_title == module_title,
            RecommendationAction.module_url == module_url,
            RecommendationAction.created_at >= duplicate_cutoff,
        )
        .first()
        is not None
    )
    if is_duplicate:
        return {"ok": True, "deduped": True}

    row = RecommendationAction(
        user_id=current_user.id,
        dimension_key=payload.dimension_key,
        module_title=module_title,
        module_url=module_url,
        action=action,
        rating=payload.rating,
        feedback=clean_feedback,
    )
    db.add(row)
    db.commit()
    return {"ok": True}

@router.get("/quests/daily", response_model=QuestListOut)
def get_daily_quests(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    now = dt.datetime.utcnow()
    day_start = dt.datetime(now.year, now.month, now.day)
    day_end = day_start + dt.timedelta(days=1)
    date_key = day_start.date().isoformat()
    claimed_rows = (
        db.query(DailyQuestClaim)
        .filter(DailyQuestClaim.user_id == current_user.id, DailyQuestClaim.quest_date == date_key)
        .all()
    )
    claimed_map = {row.quest_key: row for row in claimed_rows}
    quests = []
    for quest in DAILY_QUESTS:
        key = quest["key"]
        completed = _daily_quest_completed(db, current_user.id, key, day_start, day_end)
        quests.append(
            {
                "key": key,
                "title": quest["title"],
                "description": quest["description"],
                "reward_xp": quest["reward_xp"],
                "completed": completed,
                "claimed": key in claimed_map,
            }
        )
    return {"username": current_user.username, "date": date_key, "quests": quests}


@router.post("/quests/daily/claim")
def claim_daily_quest(
    payload: QuestClaimIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    quest = next((item for item in DAILY_QUESTS if item["key"] == payload.quest_key), None)
    if not quest:
        raise HTTPException(status_code=404, detail="Quest not found")
    now = dt.datetime.utcnow()
    day_start = dt.datetime(now.year, now.month, now.day)
    day_end = day_start + dt.timedelta(days=1)
    date_key = day_start.date().isoformat()
    claimed = (
        db.query(DailyQuestClaim)
        .filter(
            DailyQuestClaim.user_id == current_user.id,
            DailyQuestClaim.quest_key == payload.quest_key,
            DailyQuestClaim.quest_date == date_key,
        )
        .one_or_none()
    )
    if claimed:
        return {"ok": True, "already_claimed": True}
    if not _daily_quest_completed(db, current_user.id, payload.quest_key, day_start, day_end):
        raise HTTPException(status_code=400, detail="Quest is not completed yet")

    db.add(
        DailyQuestClaim(
            user_id=current_user.id,
            quest_key=payload.quest_key,
            quest_date=date_key,
            reward_xp=quest["reward_xp"],
        )
    )
    _add_bonus_xp(db, current_user, quest["reward_xp"], f"daily_quest:{payload.quest_key}")
    db.commit()
    return {"ok": True, "claimed": True, "reward_xp": quest["reward_xp"]}


@router.get("/challenges/weekly", response_model=ChallengeListOut)
def get_weekly_challenges(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    week_start_dt = week_start_for_date(dt.datetime.utcnow())
    week_key = week_start_dt.date().isoformat()
    claimed_rows = (
        db.query(WeeklyChallengeClaim)
        .filter(WeeklyChallengeClaim.user_id == current_user.id, WeeklyChallengeClaim.week_start == week_key)
        .all()
    )
    claimed_map = {row.challenge_key: row for row in claimed_rows}
    challenges = []
    for challenge in WEEKLY_CHALLENGES:
        key = challenge["key"]
        completed = _weekly_challenge_completed(db, current_user.id, key, week_start_dt)
        challenges.append(
            {
                "key": key,
                "title": challenge["title"],
                "description": challenge["description"],
                "reward_xp": challenge["reward_xp"],
                "completed": completed,
                "claimed": key in claimed_map,
            }
        )
    return {"username": current_user.username, "week_start": week_key, "challenges": challenges}


@router.post("/challenges/weekly/claim")
def claim_weekly_challenge(
    payload: ChallengeClaimIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    challenge = next((item for item in WEEKLY_CHALLENGES if item["key"] == payload.challenge_key), None)
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")
    week_start_dt = week_start_for_date(dt.datetime.utcnow())
    week_key = week_start_dt.date().isoformat()
    claimed = (
        db.query(WeeklyChallengeClaim)
        .filter(
            WeeklyChallengeClaim.user_id == current_user.id,
            WeeklyChallengeClaim.challenge_key == payload.challenge_key,
            WeeklyChallengeClaim.week_start == week_key,
        )
        .one_or_none()
    )
    if claimed:
        return {"ok": True, "already_claimed": True}
    if not _weekly_challenge_completed(db, current_user.id, payload.challenge_key, week_start_dt):
        raise HTTPException(status_code=400, detail="Challenge is not completed yet")

    db.add(
        WeeklyChallengeClaim(
            user_id=current_user.id,
            challenge_key=payload.challenge_key,
            week_start=week_key,
            reward_xp=challenge["reward_xp"],
        )
    )
    _add_bonus_xp(db, current_user, challenge["reward_xp"], f"weekly_challenge:{payload.challenge_key}")
    db.commit()
    return {"ok": True, "claimed": True, "reward_xp": challenge["reward_xp"]}


@router.get("/learning-path/projects/{username}", response_model=ProjectLearningPathResponse)
def get_project_learning_paths(
    username: str,
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.username == username).one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    db.add(ActivityLog(user_id=user.id, event="project_learning_path_view"))
    db.commit()

    portfolio_settings = _get_or_create_portfolio_settings(db, user.id)
    repos = db.query(Repo).filter(Repo.user_id == user.id).all()
    practice_rows = db.query(PracticeDimension).filter(PracticeDimension.user_id == user.id).all()
    inference_summaries = _repo_summaries_for_inference(repos)
    summaries = [
        {
            "name": item.get("name"),
            "description": item.get("description"),
            "language": item.get("language"),
            "languages": item.get("languages"),
            "topics": item.get("topics"),
            "code_signals": item.get("code_signals") or {},
            "commit_count": item.get("commit_count"),
        }
        for item in inference_summaries
    ]
    detected_skills = []
    project_keywords = []
    for repo in summaries:
        langs = repo.get("languages") or []
        if isinstance(langs, list):
            detected_skills.extend([str(lang) for lang in langs if lang])
        if repo.get("language"):
            detected_skills.append(str(repo.get("language")))
        project_keywords.extend([str(topic) for topic in (repo.get("topics") or []) if topic])
        code_signals = repo.get("code_signals") or {}
        project_keywords.extend([str(keyword) for keyword in (code_signals.get("keywords") or []) if keyword])
        detected_skills.extend([str(framework) for framework in (code_signals.get("frameworks") or []) if framework])
        project_keywords.extend([str(repo.get("name") or ""), str(repo.get("description") or "")])

    practice_dimensions = [
        {"label": item.label, "confidence": item.confidence, "evidence": item.evidence}
        for item in practice_rows
    ]

    projects = infer_project_learning_paths(
        summaries,
        detected_skills=detected_skills,
        project_keywords=project_keywords,
        practice_dimensions=practice_dimensions,
        personalization_key=username,
    )
    project_baseline = dict(portfolio_settings.project_learning_path_baseline or {})
    if not projects and isinstance(project_baseline, dict):
        cached_projects: list[dict] = []
        for repo_name, baseline_entry in project_baseline.items():
            if not isinstance(baseline_entry, dict):
                continue
            cached_steps = baseline_entry.get("steps")
            if not isinstance(cached_steps, list) or not cached_steps:
                continue
            cached_projects.append(
                {
                    "repo_name": str(repo_name or "Unnamed repo"),
                    "steps": cached_steps,
                    "progress_percent": 0,
                }
            )
        if cached_projects:
            projects = cached_projects

    projects_with_progress = []

    for project in projects:
        repo_name = project.get("repo_name") or "Unnamed repo"
        repo = next((item for item in summaries if item.get("name") == repo_name), None)
        repo_signals = build_signal_set([repo] if repo else [], include_repo_identity=False)
        repo_signals.add(f"personalization:{username}")
        baseline_key = _project_baseline_key(project_baseline, repo_name)
        baseline_entry = project_baseline.get(baseline_key) or []
        baseline_signals_list: list[str] = []
        cached_signals_list: list[str] = []
        cached_steps: list[dict] | None = None
        if isinstance(baseline_entry, dict):
            baseline_signals_list = list(baseline_entry.get("baseline_signals") or [])
            cached_signals_list = list(baseline_entry.get("latest_signals") or baseline_signals_list)
            raw_steps = baseline_entry.get("steps")
            if isinstance(raw_steps, list):
                cached_steps = raw_steps
        else:
            baseline_signals_list = list(baseline_entry or [])
            cached_signals_list = list(baseline_signals_list)
        path_level = int(baseline_entry.get("path_level") or 1) if isinstance(baseline_entry, dict) else 1
        repo_completed = bool(baseline_entry.get("repo_completed")) if isinstance(baseline_entry, dict) else False
        repo_completed_at = str(baseline_entry.get("repo_completed_at") or "") if isinstance(baseline_entry, dict) else ""
        stage_status_overrides = baseline_entry.get("stage_status_overrides") if isinstance(baseline_entry, dict) else {}
        if not isinstance(stage_status_overrides, dict):
            stage_status_overrides = {}
        stage_checks = baseline_entry.get("stage_checks") if isinstance(baseline_entry, dict) else {}
        if not isinstance(stage_checks, dict):
            stage_checks = {}
        stage_proof_counts = baseline_entry.get("stage_proof_counts") if isinstance(baseline_entry, dict) else {}
        if not isinstance(stage_proof_counts, dict):
            stage_proof_counts = {}
        stage_progress_updates = baseline_entry.get("stage_progress_updates") if isinstance(baseline_entry, dict) else {}
        if not isinstance(stage_progress_updates, dict):
            stage_progress_updates = {}

        baseline_signals = set(baseline_signals_list)
        if not baseline_signals:
            steps = [{**step, "status": "todo"} for step in (project.get("steps") or [])]
            project_baseline[baseline_key] = {
                "baseline_signals": list(repo_signals),
                "latest_signals": list(repo_signals),
                "steps": project.get("steps") or [],
                "path_level": path_level,
                "stage_status_overrides": stage_status_overrides,
                "stage_checks": stage_checks,
                "stage_proof_counts": stage_proof_counts,
                "stage_progress_updates": stage_progress_updates,
            }
            progress_percent = 0
        elif repo_completed:
            steps = [{**step, "status": "done"} for step in (cached_steps or project.get("steps") or [])]
            progress_percent = 100 if steps else 0
        else:
            if cached_steps and set(cached_signals_list) == set(repo_signals):
                steps_source = cached_steps
            else:
                steps_source = project.get("steps") or []
                project_baseline[baseline_key] = {
                    "baseline_signals": baseline_signals_list,
                    "latest_signals": list(repo_signals),
                    "steps": steps_source,
                    "path_level": path_level,
                    "stage_status_overrides": stage_status_overrides,
                    "stage_checks": stage_checks,
                    "stage_proof_counts": stage_proof_counts,
                    "stage_progress_updates": stage_progress_updates,
                }
            new_signals = repo_signals - baseline_signals
            steps, progress_percent = annotate_steps_with_status(steps_source, new_signals)
        projects_with_progress.append(
            {
                "repo_name": repo_name,
                "steps": steps,
                "progress_percent": progress_percent,
                "path_level": path_level,
                "repo_completed": repo_completed,
                "repo_completed_at": repo_completed_at or None,
                "stage_status_overrides": {str(key): str(value) for key, value in stage_status_overrides.items()},
                "stage_checks": {
                    str(key): [bool(item) for item in value]
                    for key, value in stage_checks.items()
                    if isinstance(value, list)
                },
                "stage_proof_counts": {
                    str(key): max(0, int(value or 0))
                    for key, value in stage_proof_counts.items()
                    if isinstance(value, int)
                },
                "stage_progress_updates": stage_progress_updates,
            }
        )
    portfolio_settings.project_learning_path_baseline = {**project_baseline}
    flag_modified(portfolio_settings, "project_learning_path_baseline")
    db.commit()
    return {"username": user.username, "projects": projects_with_progress}


@router.get("/certificate-suggestions/{username}", response_model=CertificateSuggestionListOut)
def get_certificate_suggestions(
    username: str,
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.username == username).one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    repos = db.query(Repo).filter(Repo.user_id == user.id).all()
    practice_rows = db.query(PracticeDimension).filter(PracticeDimension.user_id == user.id).all()
    career_rows = (
        db.query(CareerSuggestion)
        .filter(CareerSuggestion.user_id == user.id)
        .order_by(CareerSuggestion.confidence.desc(), CareerSuggestion.id.asc())
        .all()
    )
    inference_summaries = _repo_summaries_for_inference(repos)
    summaries = [
        {
            "name": item.get("name"),
            "description": item.get("description"),
            "language": item.get("language"),
            "languages": item.get("languages"),
            "topics": item.get("topics"),
            "code_signals": item.get("code_signals") or {},
            "commit_count": item.get("commit_count"),
        }
        for item in inference_summaries
    ]
    detected_skills: list[str] = []
    project_keywords: list[str] = []
    for repo in summaries:
        langs = repo.get("languages") or []
        if isinstance(langs, list):
            detected_skills.extend([str(lang) for lang in langs if lang])
        if repo.get("language"):
            detected_skills.append(str(repo.get("language")))
        project_keywords.extend([str(topic) for topic in (repo.get("topics") or []) if topic])
        code_signals = repo.get("code_signals") or {}
        project_keywords.extend([str(keyword) for keyword in (code_signals.get("keywords") or []) if keyword])
        detected_skills.extend([str(framework) for framework in (code_signals.get("frameworks") or []) if framework])
        project_keywords.extend([str(repo.get("name") or ""), str(repo.get("description") or "")])

    practice_dimensions = [
        {"label": item.label, "confidence": item.confidence, "evidence": item.evidence}
        for item in practice_rows
    ]
    career_suggestions = [
        {"title": item.title, "confidence": item.confidence, "reasoning": item.reasoning}
        for item in career_rows
    ]

    learning_steps = infer_learning_path(
        summaries,
        detected_skills=detected_skills,
        project_keywords=project_keywords,
        practice_dimensions=practice_dimensions,
    )
    project_paths = infer_project_learning_paths(
        summaries,
        detected_skills=detected_skills,
        project_keywords=project_keywords,
        practice_dimensions=practice_dimensions,
    )
    items = llm_refiner.generate_certificate_suggestions(
        learning_path_steps=learning_steps,
        project_learning_paths=project_paths,
        career_suggestions=career_suggestions,
    )
    locked_rows = (
        db.query(CertificateRecord)
        .filter(
            CertificateRecord.user_id == user.id,
            CertificateRecord.completion_locked.is_(True),
        )
        .all()
    )
    locked_by_track_id = {
        str(row.suggestion_track_id or "").strip(): row
        for row in locked_rows
        if str(row.suggestion_track_id or "").strip()
    }
    locked_by_module_url = {
        str(row.suggestion_module_url or "").strip(): row
        for row in locked_rows
        if str(row.suggestion_module_url or "").strip()
    }
    for item in items:
        item_id = str(item.get("id") or "").strip()
        item_url = str(item.get("url") or "").strip()
        locked_row = locked_by_track_id.get(item_id) or locked_by_module_url.get(item_url)
        item["completed"] = bool(locked_row)
        item["locked"] = bool(locked_row)
        item["claimed_reward_xp"] = (
            int(getattr(locked_row, "completion_reward_xp", 0) or 0)
            if locked_row and getattr(locked_row, "rewarded_at", None)
            else 0
        )
    return {"username": user.username, "items": items}


@router.post("/learning-path/projects/claim-reward", response_model=ProjectLearningPathClaimOut)
def claim_project_learning_path_reward(
    payload: ProjectLearningPathClaimIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    repo_name = str(payload.repo_name or "").strip()
    if not repo_name:
        raise HTTPException(status_code=400, detail="repo_name is required")

    portfolio_settings = _get_or_create_portfolio_settings(db, current_user.id)
    repos = db.query(Repo).filter(Repo.user_id == current_user.id).all()
    inference_summaries = _repo_summaries_for_inference(repos)
    summaries = [
        {
            "name": item.get("name"),
            "description": item.get("description"),
            "language": item.get("language"),
            "languages": item.get("languages"),
            "topics": item.get("topics"),
            "code_signals": item.get("code_signals") or {},
            "commit_count": item.get("commit_count"),
        }
        for item in inference_summaries
    ]
    repo_summary = next((item for item in summaries if str(item.get("name") or "").strip() == repo_name), None)
    if not repo_summary:
        raise HTTPException(status_code=404, detail="Repository not found")

    project_baseline = dict(portfolio_settings.project_learning_path_baseline or {})
    baseline_key = _project_baseline_key(project_baseline, repo_name)
    baseline_entry = project_baseline.get(baseline_key)
    if not isinstance(baseline_entry, dict):
        raise HTTPException(status_code=404, detail="Learning path for this repository was not found")

    current_steps = baseline_entry.get("steps")
    if not isinstance(current_steps, list) or not current_steps:
        raise HTTPException(status_code=400, detail="No claimable learning path was found for this repository")

    if bool(baseline_entry.get("repo_completed")):
        raise HTTPException(status_code=400, detail="This repository path is already completed")

    stage_status_overrides = baseline_entry.get("stage_status_overrides")
    if not isinstance(stage_status_overrides, dict) or not stage_status_overrides:
        raise HTTPException(status_code=400, detail="Complete all skill stages before claiming the repo reward")
    if any(not _is_project_stage_claim_complete(value) for value in stage_status_overrides.values()):
        raise HTTPException(status_code=400, detail="Complete all skill stages before claiming the repo reward")

    stage_proof_counts = baseline_entry.get("stage_proof_counts")
    if not isinstance(stage_proof_counts, dict) or len(stage_proof_counts) < len(stage_status_overrides):
        raise HTTPException(status_code=400, detail="Save proof in every completed stage before claiming the repo reward")
    missing_proof = [key for key in stage_status_overrides.keys() if int(stage_proof_counts.get(key) or 0) <= 0]
    if missing_proof:
        raise HTTPException(status_code=400, detail="Save proof in every completed stage before claiming the repo reward")
    stage_progress_updates = baseline_entry.get("stage_progress_updates")
    if not isinstance(stage_progress_updates, dict):
        stage_progress_updates = {}
    current_path_level = max(1, int(baseline_entry.get("path_level") or 1))
    claimed_xp = sum(max(0, int(step.get("reward_xp") or step.get("estimated_xp") or 0)) for step in current_steps)
    if claimed_xp <= 0:
        raise HTTPException(status_code=400, detail="No XP reward is available for this repository path")

    practice_rows = db.query(PracticeDimension).filter(PracticeDimension.user_id == current_user.id).all()
    practice_dimensions = [
        {"label": item.label, "confidence": item.confidence, "evidence": item.evidence}
        for item in practice_rows
    ]
    repo_signals = build_signal_set([repo_summary], include_repo_identity=False)
    claimed_at = dt.datetime.now(dt.timezone.utc).isoformat()

    completed_cycles = baseline_entry.get("completed_cycles")
    if not isinstance(completed_cycles, list):
        completed_cycles = []
    completed_cycles.append(
        {
            "path_level": current_path_level,
            "claimed_xp": claimed_xp,
            "claimed_at": claimed_at,
            "steps": current_steps,
            "stage_status_overrides": stage_status_overrides,
            "stage_checks": baseline_entry.get("stage_checks") if isinstance(baseline_entry.get("stage_checks"), dict) else {},
            "stage_proof_counts": stage_proof_counts,
            "stage_progress_updates": baseline_entry.get("stage_progress_updates") if isinstance(baseline_entry.get("stage_progress_updates"), dict) else {},
        }
    )

    repo_completed = current_path_level >= MAX_PROJECT_PATH_LEVEL
    next_path_level: int | None = None

    if repo_completed:
        project_baseline[baseline_key] = {
            **baseline_entry,
            "baseline_signals": list(repo_signals),
            "latest_signals": list(repo_signals),
            "steps": current_steps,
            "path_level": current_path_level,
            "repo_completed": True,
            "repo_completed_at": claimed_at,
            "completed_cycles": completed_cycles[-10:],
            "last_claimed_xp": claimed_xp,
            "last_claimed_at": claimed_at,
        }
    else:
        next_projects = infer_project_learning_paths([repo_summary], practice_dimensions=practice_dimensions)
        next_steps_source = next_projects[0].get("steps") if next_projects else []
        next_path_level = current_path_level + 1
        next_steps = _raise_project_path_difficulty(next_steps_source if isinstance(next_steps_source, list) else [], next_path_level)
        project_baseline[baseline_key] = {
            **baseline_entry,
            "baseline_signals": list(repo_signals),
            "latest_signals": list(repo_signals),
            "steps": next_steps,
            "path_level": next_path_level,
            "repo_completed": False,
            "repo_completed_at": None,
            "completed_cycles": completed_cycles[-10:],
            "last_claimed_xp": claimed_xp,
            "last_claimed_at": claimed_at,
            "stage_status_overrides": {},
            "stage_checks": {},
            "stage_proof_counts": {},
            "stage_progress_updates": {},
        }

    _add_bonus_xp(db, current_user, claimed_xp, f"project_learning_path_claim:{repo_name}:level_{current_path_level}")
    portfolio_settings.project_learning_path_baseline = {**project_baseline}
    flag_modified(portfolio_settings, "project_learning_path_baseline")
    db.add(ActivityLog(user_id=current_user.id, event="project_learning_path_claim", meta={"repo_name": repo_name, "claimed_xp": claimed_xp, "previous_path_level": current_path_level, "next_path_level": next_path_level, "repo_completed": repo_completed}))
    db.commit()
    return {
        "repo_name": repo_name,
        "claimed_xp": claimed_xp,
        "next_path_level": next_path_level,
        "repo_completed": repo_completed,
        "claimed_at": claimed_at,
    }


@router.post("/learning-path/projects/reset-stages", response_model=ProjectStageResetOut)
def reset_project_learning_path_stages(
    payload: ProjectStageResetIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    repo_name = str(payload.repo_name or "").strip()
    stage_titles = [
        str(title or "").strip()
        for title in (payload.stage_titles or [])
        if str(title or "").strip()
    ]
    if not repo_name or not stage_titles:
        raise HTTPException(status_code=400, detail="repo_name and at least one stage title are required")

    portfolio_settings = _get_or_create_portfolio_settings(db, current_user.id)
    project_baseline = dict(portfolio_settings.project_learning_path_baseline or {})
    baseline_key = _project_baseline_key(project_baseline, repo_name)
    baseline_entry = project_baseline.get(baseline_key)
    if not isinstance(baseline_entry, dict):
        raise HTTPException(status_code=404, detail="Learning path for this repository was not found")

    stage_status_overrides = baseline_entry.get("stage_status_overrides")
    if not isinstance(stage_status_overrides, dict):
        stage_status_overrides = {}
    stage_checks = baseline_entry.get("stage_checks")
    if not isinstance(stage_checks, dict):
        stage_checks = {}
    stage_proof_counts = baseline_entry.get("stage_proof_counts")
    if not isinstance(stage_proof_counts, dict):
        stage_proof_counts = {}
    stage_progress_updates = baseline_entry.get("stage_progress_updates")
    if not isinstance(stage_progress_updates, dict):
        stage_progress_updates = {}

    reset_titles: list[str] = []
    for stage_title in stage_titles:
        stage_status_overrides[stage_title] = "not_started"
        stage_checks[stage_title] = []
        stage_proof_counts.pop(stage_title, None)
        stage_progress_updates.pop(stage_title, None)
        reset_titles.append(stage_title)

    baseline_entry["stage_status_overrides"] = stage_status_overrides
    baseline_entry["stage_checks"] = stage_checks
    baseline_entry["stage_proof_counts"] = stage_proof_counts
    baseline_entry["stage_progress_updates"] = stage_progress_updates
    project_baseline[baseline_key] = baseline_entry
    portfolio_settings.project_learning_path_baseline = {**project_baseline}
    flag_modified(portfolio_settings, "project_learning_path_baseline")
    db.add(
        ActivityLog(
            user_id=current_user.id,
            event="project_learning_path_stage_reset",
            meta={"repo_name": repo_name, "stage_titles": reset_titles},
        )
    )
    db.commit()
    return {
        "repo_name": repo_name,
        "stage_titles": reset_titles,
    }
