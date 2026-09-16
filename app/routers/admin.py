from fastapi import APIRouter, Depends, HTTPException, Query, Response, Body
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
import datetime as dt
import csv
import io
from pathlib import Path

from app.core.config import settings
from app.core.dependencies import get_current_admin
from app.db import get_db
from app.models import (
    User,
    Repo,
    Badge,
    AdminNote,
    ProjectValidation,
    PortfolioReview,
    AdminAccount,
    ActivityLog,
    CertificateRecord,
    FccModuleProgress,
    RecommendationAction,
    PracticeDimension,
    CareerSuggestion,
    PortfolioSettings,
    EngagementCommit,
    LearningProgress,
    DailyQuestClaim,
    WeeklyChallengeClaim,
    XpHistory,
    LoginActivity,
)
from app.schemas import (
    AdminStudentSummary,
    AdminNoteIn,
    AdminNoteOut,
    ProjectValidationIn,
    ProjectValidationOut,
    PortfolioReviewIn,
    PortfolioReviewOut,
    StudentVerifyIn,
    StudentVerifyOut,
    AdminAnalyticsOut,
    AdminDeepAnalyticsOut,
    AdminAnalyticsDay,
    AdminAnalyticsLabel,
    CertificateOut,
    CertificateReviewIn,
    CertificateCommentIn,
    CertificateCommentDeleteIn,
    AdminEvaluationMetricsOut,
    AdminEvaluationPredictionsOut,
    AdminEvaluationPredictionSampleOut,
    ValidationBulkIn,
    CertificateReviewBulkIn,
    ResearchAnalyticsOut,
    AdminStudentDetailOut,
    AdminStudentDetailProfileOut,
    AdminStudentDetailOverviewOut,
    AdminStudentRecommendationActionOut,
    AdminStudentActivityItemOut,
    FccModuleProgressOut,
    FccModuleProgressSummaryOut,
    AdminStageFeedbackIn,
    AdminStageFeedbackDeleteIn,
    AdminStageFeedbackOut,
)
from app.services.gamification import level_from_xp
from sqlalchemy.orm.attributes import flag_modified


router = APIRouter(prefix="/admin", tags=["admin"])

ADOPTED_RECOMMENDATION_ACTIONS = {"clicked", "accepted", "completed", "started"}
ONLINE_WINDOW = dt.timedelta(seconds=45)


def _project_baseline_key(project_baseline: dict, repo_name: str) -> str:
    clean_name = str(repo_name or "").strip()
    clean_lower = clean_name.lower()
    for key in project_baseline.keys():
        if str(key).strip().lower() == clean_lower:
            return str(key)
    return clean_name

EVALUATION_METRICS_PATH = Path(__file__).resolve().parents[2] / "evaluation" / "evaluation_metrics.csv"
TEST_PREDICTIONS_PATH = Path(__file__).resolve().parents[2] / "evaluation" / "test_predictions.csv"


def _now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


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
        "status": row.status,
        "reviewer_note": row.reviewer_note,
        "submitted_at": str(row.submitted_at),
        "verified_at": str(row.verified_at) if row.verified_at else None,
        "comment_thread": thread_meta.get("comment_thread") if isinstance(thread_meta.get("comment_thread"), list) else [],
        "latest_admin_comment_at": thread_meta.get("latest_admin_comment_at"),
        "latest_student_reply_at": thread_meta.get("latest_student_reply_at"),
    }


def _as_utc(value: dt.datetime | None) -> dt.datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)


def _elapsed_since(value: dt.datetime | None, now: dt.datetime) -> dt.timedelta | None:
    timestamp = _as_utc(value)
    if timestamp is None:
        return None
    return now - timestamp


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


def _student_users_query(db: Session):
    # Backward-compatible student filter:
    # include legacy rows where role can be null/empty, and explicit "student" rows.
    return db.query(User).filter(
        or_(
            User.role.is_(None),
            User.role == "",
            func.lower(User.role) == "student",
        )
    )


def _latest_logout_map(db: Session, user_ids: list[int]) -> dict[int, dt.datetime]:
    if not user_ids:
        return {}
    rows = (
        db.query(ActivityLog.user_id, func.max(ActivityLog.created_at))
        .filter(ActivityLog.user_id.in_(user_ids), ActivityLog.event == "logout")
        .group_by(ActivityLog.user_id)
        .all()
    )
    return {int(user_id): logged_out_at for user_id, logged_out_at in rows if user_id and logged_out_at}


def _is_student_online(last_seen: dt.datetime | None, last_logout_at: dt.datetime | None, now: dt.datetime) -> bool:
    elapsed = _elapsed_since(last_seen, now)
    if elapsed is None or elapsed > ONLINE_WINDOW:
        return False
    logout_at = _as_utc(last_logout_at)
    seen_at = _as_utc(last_seen)
    if logout_at is not None and seen_at is not None and logout_at >= seen_at:
        return False
    return True


def _load_ai_evaluation_metrics() -> dict:
    if not EVALUATION_METRICS_PATH.exists():
        return {}
    try:
        with EVALUATION_METRICS_PATH.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except Exception:
        return {}
    if not rows:
        return {}
    row = rows[0]

    def as_int(key: str) -> int | None:
        try:
            value = row.get(key)
            return int(float(value)) if value not in {None, ""} else None
        except (TypeError, ValueError):
            return None

    def as_float(key: str) -> float | None:
        try:
            value = row.get(key)
            return float(value) if value not in {None, ""} else None
        except (TypeError, ValueError):
            return None

    return {
        "ai_eval_model": row.get("model") or None,
        "ai_eval_dataset_rows": as_int("dataset_rows"),
        "ai_eval_train_rows": as_int("train_rows"),
        "ai_eval_validation_rows": as_int("validation_rows"),
        "ai_eval_test_rows": as_int("test_rows"),
        "rouge1": as_float("rouge1"),
        "rouge2": as_float("rouge2"),
        "rougeL": as_float("rougeL"),
        "bleu": as_float("bleu"),
        "bertscore_precision": as_float("bertscore_precision"),
        "bertscore_recall": as_float("bertscore_recall"),
        "bertscore_f1": as_float("bertscore_f1"),
    }


def _load_ai_prediction_samples(limit: int = 12) -> dict:
    if not TEST_PREDICTIONS_PATH.exists():
        return {"total_rows": 0, "sample_count": 0, "samples": []}
    try:
        with TEST_PREDICTIONS_PATH.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except Exception:
        return {"total_rows": 0, "sample_count": 0, "samples": []}

    samples: list[AdminEvaluationPredictionSampleOut] = []
    for index, row in enumerate(rows[: max(1, limit)], start=1):
        samples.append(
            AdminEvaluationPredictionSampleOut(
                row_number=index,
                input=(row.get("input") or "").strip(),
                output=(row.get("output") or "").strip() or None,
                prediction=(row.get("prediction") or "").strip() or None,
                reference=(row.get("reference") or "").strip() or None,
            )
        )

    return {
        "total_rows": len(rows),
        "sample_count": len(samples),
        "samples": samples,
    }


@router.delete("/students")
def delete_all_students(
    confirm: str = Body(..., embed=True),
    db: Session = Depends(get_db),
    current_admin: AdminAccount = Depends(get_current_admin),
):
    """Dangerous: delete all student users and related data.

    Requires JSON body: { "confirm": "DELETE_ALL_STUDENTS" }
    """
    if confirm != "DELETE_ALL_STUDENTS":
        raise HTTPException(status_code=400, detail="Missing or invalid confirmation token")

    students = _student_users_query(db).all()
    if not students:
        return {"deleted": 0}

    deleted_count = 0
    for user in students:
        # Remove admin notes, validations, reviews, certificates, activity logs, recommendations
        db.query(AdminNote).filter(AdminNote.student_id == user.id).delete()
        db.query(ProjectValidation).filter(ProjectValidation.student_id == user.id).delete()
        db.query(PortfolioReview).filter(PortfolioReview.student_id == user.id).delete()
        db.query(CertificateRecord).filter(CertificateRecord.user_id == user.id).delete()
        db.query(FccModuleProgress).filter(FccModuleProgress.user_id == user.id).delete()
        db.query(ActivityLog).filter(ActivityLog.user_id == user.id).delete()
        db.query(RecommendationAction).filter(RecommendationAction.user_id == user.id).delete()

        # Engagement + learning history
        db.query(EngagementCommit).filter(EngagementCommit.user_id == user.id).delete()
        db.query(LearningProgress).filter(LearningProgress.user_id == user.id).delete()
        db.query(DailyQuestClaim).filter(DailyQuestClaim.user_id == user.id).delete()
        db.query(WeeklyChallengeClaim).filter(WeeklyChallengeClaim.user_id == user.id).delete()
        db.query(XpHistory).filter(XpHistory.user_id == user.id).delete()
        db.query(LoginActivity).filter(LoginActivity.user_id == user.id).delete()

        # Repos, badges, practice dimensions, career suggestions, portfolio settings
        db.query(Repo).filter(Repo.user_id == user.id).delete(synchronize_session=False)
        db.query(Badge).filter(Badge.user_id == user.id).delete()
        db.query(PracticeDimension).filter(PracticeDimension.user_id == user.id).delete()
        db.query(CareerSuggestion).filter(CareerSuggestion.user_id == user.id).delete()
        db.query(PortfolioSettings).filter(PortfolioSettings.user_id == user.id).delete()

        # Finally remove the user
        db.query(User).filter(User.id == user.id).delete()
        deleted_count += 1

    db.commit()
    return {"deleted": deleted_count}


@router.get("/students", response_model=list[AdminStudentSummary])
def list_students(
    db: Session = Depends(get_db),
    current_admin: AdminAccount = Depends(get_current_admin),
):
    users = _student_users_query(db).all()
    logout_by_user = _latest_logout_map(db, [user.id for user in users])
    summaries: list[AdminStudentSummary] = []
    now = _now_utc()
    for user in users:
        repo_count = db.query(Repo).filter(Repo.user_id == user.id).count()
        badges_claimed = db.query(Badge).filter(
            Badge.user_id == user.id, Badge.claimed.is_(True)
        ).count()
        total_xp = 0
        for repo in db.query(Repo).filter(Repo.user_id == user.id).all():
            total_xp += int(repo.commit_count or 0) * 2
            total_xp += 50
            total_xp += int(repo.stars or 0)
        total_xp += int(user.bonus_xp or 0)
        level = level_from_xp(total_xp)
        last_seen = user.last_seen
        online = _is_student_online(last_seen, logout_by_user.get(user.id), now)
        summaries.append(
            AdminStudentSummary(
                id=user.id,
                username=user.username,
                display_name=user.display_name,
                avatar_url=user.avatar_url,
                level=level,
                xp=total_xp,
                repo_count=repo_count,
                badges_claimed=badges_claimed,
                online=online,
                last_seen=str(last_seen) if last_seen else None,
                program=user.program,
                year_level=user.year_level,
                is_verified=bool(user.is_verified),
                verified_at=str(user.verified_at) if user.verified_at else None,
            )
        )
    return summaries


@router.get("/students/{student_id}/details", response_model=AdminStudentDetailOut)
def get_student_details(
    student_id: int,
    db: Session = Depends(get_db),
    current_admin: AdminAccount = Depends(get_current_admin),
):
    student = _student_users_query(db).filter(User.id == student_id).one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    portfolio_settings = db.query(PortfolioSettings).filter(PortfolioSettings.user_id == student.id).one_or_none()
    social_links = (portfolio_settings.social_links or {}) if portfolio_settings else {}
    if not isinstance(social_links, dict):
        social_links = {}

    repos = db.query(Repo).filter(Repo.user_id == student.id).all()
    badges_claimed = db.query(Badge).filter(Badge.user_id == student.id, Badge.claimed.is_(True)).count()
    total_commits = sum(int(repo.commit_count or 0) for repo in repos)
    total_stars = sum(int(repo.stars or 0) for repo in repos)
    xp = int(student.bonus_xp or 0)
    for repo in repos:
        xp += int(repo.commit_count or 0) * 2
        xp += 50
        xp += int(repo.stars or 0)
    level = level_from_xp(xp)

    certificates = (
        db.query(CertificateRecord)
        .filter(CertificateRecord.user_id == student.id)
        .order_by(CertificateRecord.submitted_at.desc())
        .limit(100)
        .all()
    )
    certificates_verified = sum(1 for row in certificates if row.status == "verified")
    fcc_progress_rows = (
        db.query(FccModuleProgress)
        .filter(FccModuleProgress.user_id == student.id)
        .order_by(FccModuleProgress.module_title.asc(), FccModuleProgress.id.asc())
        .all()
    )

    recommendation_rows = (
        db.query(RecommendationAction)
        .filter(RecommendationAction.user_id == student.id)
        .order_by(RecommendationAction.created_at.desc())
        .limit(100)
        .all()
    )
    accepted_actions = sum(1 for row in recommendation_rows if row.action in {"accepted", "completed", "started"})
    rated_rows = [row for row in recommendation_rows if row.rating is not None]
    relevant_rows = [row for row in rated_rows if int(row.rating or 0) >= 4]

    learning_views = db.query(ActivityLog).filter(
        ActivityLog.user_id == student.id,
        ActivityLog.event.in_(["learning_path_view", "project_learning_path_view"]),
    ).count()
    career_rows = (
        db.query(CareerSuggestion)
        .filter(CareerSuggestion.user_id == student.id)
        .order_by(CareerSuggestion.confidence.desc(), CareerSuggestion.title.asc())
        .all()
    )
    career_interest = (student.career_interest or "").strip()
    if not career_interest and career_rows:
        career_interest = str(career_rows[0].title or "").strip()
    profile_strength = 0
    if (student.display_name or "").strip():
        profile_strength += 20
    if (student.bio or "").strip():
        profile_strength += 20
    if career_interest:
        profile_strength += 20
    if repos:
        profile_strength += 20
    if learning_views > 0:
        profile_strength += 20
    portfolio_completeness = min(100, profile_strength)

    now = _now_utc()
    days_since_last_seen = None
    last_seen_elapsed = _elapsed_since(student.last_seen, now)
    if last_seen_elapsed is not None:
        days_since_last_seen = max(0, last_seen_elapsed.days)

    top_repos = sorted(repos, key=lambda row: (int(row.commit_count or 0), int(row.stars or 0)), reverse=True)[:6]
    validations = (
        db.query(ProjectValidation)
        .filter(ProjectValidation.student_id == student.id)
        .order_by(ProjectValidation.created_at.desc())
        .limit(50)
        .all()
    )
    notes = (
        db.query(AdminNote)
        .filter(AdminNote.student_id == student.id)
        .order_by(AdminNote.created_at.desc())
        .limit(50)
        .all()
    )
    reviews = (
        db.query(PortfolioReview)
        .filter(PortfolioReview.student_id == student.id)
        .order_by(PortfolioReview.created_at.desc())
        .limit(50)
        .all()
    )
    activity_rows = (
        db.query(ActivityLog)
        .filter(ActivityLog.user_id == student.id)
        .order_by(ActivityLog.created_at.desc())
        .limit(30)
        .all()
    )
    last_logout_at = (
        db.query(func.max(ActivityLog.created_at))
        .filter(ActivityLog.user_id == student.id, ActivityLog.event == "logout")
        .scalar()
    )

    student_summary = AdminStudentSummary(
        id=student.id,
        username=student.username,
        display_name=student.display_name,
        avatar_url=student.avatar_url,
        level=level,
        xp=xp,
        repo_count=len(repos),
        badges_claimed=badges_claimed,
        online=_is_student_online(student.last_seen, last_logout_at, now),
        last_seen=str(student.last_seen) if student.last_seen else None,
        program=student.program,
        year_level=student.year_level,
        is_verified=bool(student.is_verified),
        verified_at=str(student.verified_at) if student.verified_at else None,
    )
    certificate_thread_map = _certificate_thread_map(db, student.id, [row.id for row in certificates])

    return AdminStudentDetailOut(
        student=student_summary,
        profile=AdminStudentDetailProfileOut(
            bio=(portfolio_settings.bio if portfolio_settings and portfolio_settings.bio else student.bio),
            student_id=str(social_links.get("student_id") or student.student_id or "") or None,
            career_interest=career_interest or None,
            preferred_learning_style=student.preferred_learning_style,
            target_role=student.target_role,
            target_certifications=[str(item) for item in (student.target_certifications or [])],
            email=str(social_links.get("email") or "").strip() or None,
            linkedin=str(social_links.get("linkedin") or "").strip() or None,
            phone=str(social_links.get("phone") or "").strip() or None,
            tech_stack=[str(item).strip() for item in (social_links.get("tech_stack") or []) if str(item).strip()],
            education_history=[item for item in (social_links.get("education_history") or []) if isinstance(item, dict)],
            job_experience=[item for item in (social_links.get("job_experience") or []) if isinstance(item, dict)],
            profile_image=str(social_links.get("profile_image") or "").strip() or None,
            created_at=str(student.created_at) if student.created_at else None,
        ),
        overview=AdminStudentDetailOverviewOut(
            total_commits=total_commits,
            total_stars=total_stars,
            repo_count=len(repos),
            badges_claimed=badges_claimed,
            certificates_total=len(certificates),
            certificates_verified=certificates_verified,
            recommendation_actions_total=len(recommendation_rows),
            recommendation_acceptance_rate=int(round((accepted_actions / len(recommendation_rows)) * 100))
            if recommendation_rows
            else 0,
            recommendation_relevance_rate=int(round((len(relevant_rows) / len(rated_rows)) * 100)) if rated_rows else 0,
            portfolio_completeness=portfolio_completeness,
            days_since_last_seen=days_since_last_seen,
        ),
        top_repos=[
            {
                "name": repo.name,
                "description": repo.description,
                "language": repo.language,
                "languages": repo.languages or [],
                "language_bytes": repo.language_bytes or {},
                "code_signals": repo.code_signals or {},
                "stars": int(repo.stars or 0),
                "last_push": repo.last_push,
                "commit_count": int(repo.commit_count or 0),
            }
            for repo in top_repos
        ],
        practice_dimensions=[
            {
                "label": row.label,
                "confidence": int(row.confidence or 0),
                "evidence": [str(item) for item in (row.evidence or [])],
            }
            for row in db.query(PracticeDimension).filter(PracticeDimension.user_id == student.id).all()
        ],
        career_suggestions=[
            {
                "title": row.title,
                "confidence": int(row.confidence or 0),
                "reasoning": row.reasoning,
            }
            for row in career_rows
        ],
        recent_recommendations=[
            AdminStudentRecommendationActionOut(
                id=row.id,
                dimension_key=row.dimension_key,
                module_title=row.module_title,
                module_url=row.module_url,
                action=row.action,
                rating=row.rating,
                feedback=row.feedback,
                created_at=str(row.created_at),
            )
            for row in recommendation_rows[:20]
        ],
        recent_activity=[
            AdminStudentActivityItemOut(
                id=row.id,
                event=row.event,
                meta=row.meta or {},
                created_at=str(row.created_at),
            )
            for row in activity_rows
        ],
        fcc_progress_summary=FccModuleProgressSummaryOut(**_fcc_progress_summary(fcc_progress_rows)),
        fcc_progress=[
            FccModuleProgressOut(**_fcc_progress_payload(row))
            for row in fcc_progress_rows
        ],
        certificates=[
            _certificate_payload(row, student.username, certificate_thread_map.get(row.id))
            for row in certificates
        ],
        validations=[
            {
                "id": row.id,
                "admin_id": row.admin_id,
                "student_id": row.student_id,
                "repo_name": row.repo_name,
                "status": row.status,
                "comment": row.comment,
                "created_at": str(row.created_at),
            }
            for row in validations
        ],
        notes=[
            {
                "id": row.id,
                "admin_id": row.admin_id,
                "student_id": row.student_id,
                "note": row.note,
                "created_at": str(row.created_at),
            }
            for row in notes
        ],
        reviews=[
            {
                "id": row.id,
                "admin_id": row.admin_id,
                "student_id": row.student_id,
                "status": row.status,
                "summary": row.summary,
                "created_at": str(row.created_at),
            }
            for row in reviews
        ],
    )


@router.delete("/students/{student_id}")
def delete_student(
    student_id: int,
    db: Session = Depends(get_db),
    current_admin: AdminAccount = Depends(get_current_admin),
):
    """Delete a single student and related data.

    Only student-role users (or legacy null/empty role) may be deleted via this endpoint.
    """
    target = _student_users_query(db).filter(User.id == student_id).one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Student not found or cannot be deleted")

    # Remove admin notes, validations, reviews, certificates, activity logs, recommendations
    db.query(AdminNote).filter(AdminNote.student_id == target.id).delete()
    db.query(ProjectValidation).filter(ProjectValidation.student_id == target.id).delete()
    db.query(PortfolioReview).filter(PortfolioReview.student_id == target.id).delete()
    db.query(CertificateRecord).filter(CertificateRecord.user_id == target.id).delete()
    db.query(FccModuleProgress).filter(FccModuleProgress.user_id == target.id).delete()
    db.query(ActivityLog).filter(ActivityLog.user_id == target.id).delete()
    db.query(RecommendationAction).filter(RecommendationAction.user_id == target.id).delete()

    # Engagement + learning history
    db.query(EngagementCommit).filter(EngagementCommit.user_id == target.id).delete()
    db.query(LearningProgress).filter(LearningProgress.user_id == target.id).delete()
    db.query(DailyQuestClaim).filter(DailyQuestClaim.user_id == target.id).delete()
    db.query(WeeklyChallengeClaim).filter(WeeklyChallengeClaim.user_id == target.id).delete()
    db.query(XpHistory).filter(XpHistory.user_id == target.id).delete()
    db.query(LoginActivity).filter(LoginActivity.user_id == target.id).delete()

    # Repos, badges, practice dimensions, career suggestions, portfolio settings
    db.query(Repo).filter(Repo.user_id == target.id).delete(synchronize_session=False)
    db.query(Badge).filter(Badge.user_id == target.id).delete()
    db.query(PracticeDimension).filter(PracticeDimension.user_id == target.id).delete()
    db.query(CareerSuggestion).filter(CareerSuggestion.user_id == target.id).delete()
    db.query(PortfolioSettings).filter(PortfolioSettings.user_id == target.id).delete()

    # Finally remove the user
    db.query(User).filter(User.id == target.id).delete()
    db.commit()
    return {"deleted": student_id}


@router.post("/students/verify", response_model=StudentVerifyOut)
def verify_student(
    payload: StudentVerifyIn,
    db: Session = Depends(get_db),
    current_admin: AdminAccount = Depends(get_current_admin),
):
    student = _student_users_query(db).filter(User.id == payload.student_id).one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    student.is_verified = bool(payload.is_verified)
    student.verified_at = dt.datetime.utcnow() if payload.is_verified else None
    db.add(student)
    db.commit()
    return StudentVerifyOut(
        student_id=student.id,
        is_verified=bool(student.is_verified),
        verified_at=str(student.verified_at) if student.verified_at else None,
    )


@router.get("/analytics", response_model=AdminAnalyticsOut)
def get_analytics(
    db: Session = Depends(get_db),
    current_admin: AdminAccount = Depends(get_current_admin),
):
    total_students = _student_users_query(db).count()
    total_repos = db.query(Repo).count()
    avg_xp = 0
    avg_level = 1
    if total_students:
        xp_sum = 0
        for user in _student_users_query(db).all():
            user_xp = 0
            for repo in db.query(Repo).filter(Repo.user_id == user.id).all():
                user_xp += int(repo.commit_count or 0) * 2
                user_xp += 50
                user_xp += int(repo.stars or 0)
            user_xp += int(user.bonus_xp or 0)
            xp_sum += user_xp
        avg_xp = int(xp_sum / total_students)
        avg_level = level_from_xp(avg_xp)

    pending_validations = db.query(ProjectValidation).filter(
        ProjectValidation.status == "pending"
    ).count()

    adoption_total_users = total_students
    adoption_users = 0
    if adoption_total_users:
        student_ids = [user.id for user in _student_users_query(db).all()]
        if student_ids:
            adoption_users = len(
                {
                    row.user_id
                    for row in db.query(RecommendationAction)
                    .filter(
                        RecommendationAction.user_id.in_(student_ids),
                        RecommendationAction.action.in_(list(ADOPTED_RECOMMENDATION_ACTIONS)),
                    )
                    .all()
                }
            )
    adoption_rate = int(round((adoption_users / adoption_total_users) * 100)) if adoption_total_users else 0

    return AdminAnalyticsOut(
        total_students=total_students,
        total_repos=total_repos,
        avg_xp=avg_xp,
        avg_level=avg_level,
        pending_validations=pending_validations,
        adoption_users=adoption_users,
        adoption_total_users=adoption_total_users,
        adoption_rate=adoption_rate,
    )


@router.get("/analytics/deep", response_model=AdminDeepAnalyticsOut)
def get_deep_analytics(
    range_param: str = Query("7d", alias="range", pattern="^(1h|1d|7d|30d)$"),
    db: Session = Depends(get_db),
    current_admin: AdminAccount = Depends(get_current_admin),
):
    now = _now_utc()
    if range_param == "1h":
        bucket_seconds = 60
        bucket_count = 60
    elif range_param == "1d":
        bucket_seconds = 60 * 60
        bucket_count = 24
    elif range_param == "30d":
        bucket_seconds = 24 * 60 * 60
        bucket_count = 30
    else:
        bucket_seconds = 24 * 60 * 60
        bucket_count = 7

    start_dt = now - dt.timedelta(seconds=bucket_seconds * (bucket_count - 1))
    buckets: list[dt.datetime] = [
        start_dt + dt.timedelta(seconds=bucket_seconds * idx) for idx in range(bucket_count)
    ]
    day_map: dict[str, dict[str, int]] = {}
    login_sets: dict[str, set[int]] = {}
    for bucket in buckets:
        if bucket_seconds >= 24 * 60 * 60:
            label = bucket.date().isoformat()
        else:
            label = bucket.strftime("%H:%M")
        day_map[label] = {
            "logins": 0,
            "profile_updates": 0,
            "recomputes": 0,
            "learning_path_views": 0,
        }
        login_sets[label] = set()

    logs = db.query(ActivityLog).filter(ActivityLog.created_at >= start_dt).all()
    total_events = len(logs)
    for log in logs:
        created_at = log.created_at
        if not created_at:
            continue
        offset = int((created_at - start_dt).total_seconds() // bucket_seconds)
        if offset < 0 or offset >= bucket_count:
            continue
        bucket_dt = start_dt + dt.timedelta(seconds=bucket_seconds * offset)
        label = bucket_dt.date().isoformat() if bucket_seconds >= 24 * 60 * 60 else bucket_dt.strftime("%H:%M")
        if label not in day_map:
            continue
        if log.event in {"login", "heartbeat"}:
            login_sets[label].add(log.user_id)
        elif log.event == "profile_update":
            day_map[label]["profile_updates"] += 1
        elif log.event == "recompute":
            day_map[label]["recomputes"] += 1
        elif log.event in {"learning_path_view", "project_learning_path_view"}:
            day_map[label]["learning_path_views"] += 1

    for label, users in login_sets.items():
        day_map[label]["logins"] = len(users)

    day_rows = [
        AdminAnalyticsDay(
            date=label,
            logins=values["logins"],
            profile_updates=values["profile_updates"],
            recomputes=values["recomputes"],
            learning_path_views=values["learning_path_views"],
        )
        for label, values in day_map.items()
    ]

    language_counts: dict[str, int] = {}
    for repo in db.query(Repo).all():
        if repo.language:
            key = repo.language.strip()
            if key:
                language_counts[key] = language_counts.get(key, 0) + 1
        if isinstance(repo.languages, list):
            for lang in repo.languages:
                if not lang:
                    continue
                key = str(lang).strip()
                if not key:
                    continue
                language_counts[key] = language_counts.get(key, 0) + 1

    top_languages = sorted(
        [AdminAnalyticsLabel(label=label, count=count) for label, count in language_counts.items()],
        key=lambda item: item.count,
        reverse=True,
    )[:8]

    return AdminDeepAnalyticsOut(
        days=day_rows,
        top_languages=top_languages,
        total_events=total_events,
    )


@router.post("/analytics/reset")
def reset_analytics(
    db: Session = Depends(get_db),
    current_admin: AdminAccount = Depends(get_current_admin),
):
    db.query(ActivityLog).delete()
    db.commit()
    return {"ok": True}


@router.get("/evaluation/metrics", response_model=AdminEvaluationMetricsOut)
def get_evaluation_metrics(
    db: Session = Depends(get_db),
    current_admin: AdminAccount = Depends(get_current_admin),
):
    students = _student_users_query(db).all()
    total_students = len(students)
    student_ids = [user.id for user in students]
    portfolio_settings_rows = (
        db.query(PortfolioSettings).filter(PortfolioSettings.user_id.in_(student_ids)).all()
        if student_ids
        else []
    )
    portfolio_settings_map = {row.user_id: row for row in portfolio_settings_rows}

    action_rows = (
        db.query(RecommendationAction)
        .filter(RecommendationAction.user_id.in_(student_ids))
        .all()
        if student_ids
        else []
    )
    action_total = len(action_rows)
    accepted_actions = sum(1 for row in action_rows if row.action in {"accepted", "completed"})
    acceptance_rate = int(round((accepted_actions / action_total) * 100)) if action_total else 0
    rating_rows = [row for row in action_rows if row.rating is not None]
    relevant_rows = [row for row in rating_rows if int(row.rating or 0) >= 4]
    relevance_rate = int(round((len(relevant_rows) / len(rating_rows)) * 100)) if rating_rows else 0

    complete_portfolio_students = 0
    tracked_portfolios_total = 0
    for user in students:
        repos = db.query(Repo).filter(Repo.user_id == user.id).all()
        settings_row = portfolio_settings_map.get(user.id)
        social_links = (settings_row.social_links or {}) if settings_row and isinstance(settings_row.social_links, dict) else {}
        has_repo = len(repos) > 0
        has_commit = any(int(repo.commit_count or 0) > 0 for repo in repos)
        has_practice = db.query(ActivityLog).filter(
            ActivityLog.user_id == user.id,
            ActivityLog.event.in_(["learning_path_view", "project_learning_path_view"]),
        ).count() > 0
        has_portfolio_content = any(
            [
                (user.display_name or "").strip(),
                (user.bio or "").strip(),
                (user.student_id or "").strip(),
                (user.program or "").strip(),
                (user.year_level or "").strip(),
                (settings_row.bio or "").strip() if settings_row else "",
                len(settings_row.featured_repos or []) > 0 if settings_row else False,
                len(social_links.get("tech_stack") or []) > 0,
                len(social_links.get("education_history") or []) > 0,
                len(social_links.get("job_experience") or []) > 0,
                str(social_links.get("email") or "").strip(),
                str(social_links.get("linkedin") or "").strip(),
                str(social_links.get("phone") or "").strip(),
                has_repo,
            ]
        )
        if has_portfolio_content:
            tracked_portfolios_total += 1
        if has_repo and has_commit and has_practice:
            complete_portfolio_students += 1
    completeness_rate = int(round((complete_portfolio_students / total_students) * 100)) if total_students else 0
    ai_metrics = _load_ai_evaluation_metrics()

    return {
        "total_students": total_students,
        "ai_model_provider": settings.model_alias or "Fine-tuned FLAN-T5",
        "ai_model_name": settings.flan_t5_model or "google/flan-t5-base",
        "ai_fallback_strategy": "Deterministic rule-based fallback for invalid or unavailable model output",
        "recommendation_actions_total": action_total,
        "recommendation_acceptance_rate": acceptance_rate,
        "recommendation_ratings_total": len(rating_rows),
        "recommendation_relevance_rate": relevance_rate,
        "tracked_portfolios_total": tracked_portfolios_total,
        "portfolio_completeness_rate": completeness_rate,
        **ai_metrics,
    }


@router.get("/evaluation/predictions", response_model=AdminEvaluationPredictionsOut)
def get_evaluation_predictions(
    limit: int = Query(default=12, ge=1, le=30),
    db: Session = Depends(get_db),
    current_admin: AdminAccount = Depends(get_current_admin),
):
    return _load_ai_prediction_samples(limit=limit)


@router.post("/notes", response_model=AdminNoteOut)
def create_note(
    payload: AdminNoteIn,
    db: Session = Depends(get_db),
    current_admin: AdminAccount = Depends(get_current_admin),
):
    student = db.query(User).filter(User.id == payload.student_id).one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    note = AdminNote(admin_id=current_admin.id, student_id=student.id, note=payload.note)
    db.add(note)
    db.commit()
    db.refresh(note)
    return AdminNoteOut(
        id=note.id,
        admin_id=note.admin_id,
        student_id=note.student_id,
        note=note.note,
        created_at=str(note.created_at),
    )


@router.get("/notes/{student_id}", response_model=list[AdminNoteOut])
def list_notes(
    student_id: int,
    db: Session = Depends(get_db),
    current_admin: AdminAccount = Depends(get_current_admin),
):
    notes = db.query(AdminNote).filter(AdminNote.student_id == student_id).order_by(
        AdminNote.created_at.desc()
    )
    return [
        AdminNoteOut(
            id=note.id,
            admin_id=note.admin_id,
            student_id=note.student_id,
            note=note.note,
            created_at=str(note.created_at),
        )
        for note in notes
    ]


@router.put("/students/{username}/learning-path/stage-feedback", response_model=AdminStageFeedbackOut)
def upsert_stage_feedback(
    username: str,
    payload: AdminStageFeedbackIn,
    db: Session = Depends(get_db),
    current_admin: AdminAccount = Depends(get_current_admin),
):
    target_username = str(username or "").strip()
    repo_name = str(payload.repo_name or "").strip()
    stage_title = str(payload.stage_title or "").strip()
    feedback = str(payload.feedback or "").strip()
    review_status = str(payload.status or "").strip().lower()
    if review_status and review_status not in {"pending", "accepted", "rejected"}:
        raise HTTPException(status_code=400, detail="Invalid review status")
    if not target_username:
        raise HTTPException(status_code=400, detail="Username is required")
    if not repo_name or not stage_title:
        raise HTTPException(status_code=400, detail="repo_name and stage_title are required")
    if not feedback and not review_status:
        raise HTTPException(status_code=400, detail="Feedback or review status is required")

    student = db.query(User).filter(User.username == target_username).one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    settings_row = db.query(PortfolioSettings).filter(PortfolioSettings.user_id == student.id).one_or_none()
    if not settings_row:
        settings_row = PortfolioSettings(user_id=student.id, learning_path_baseline=[], project_learning_path_baseline={})
        db.add(settings_row)
        db.flush()

    project_baseline = dict(settings_row.project_learning_path_baseline or {})
    baseline_key = _project_baseline_key(project_baseline, repo_name)
    project_entry = project_baseline.get(baseline_key)
    if not isinstance(project_entry, dict):
        project_entry = {"baseline_signals": [], "latest_signals": [], "steps": []}

    stage_updates = project_entry.get("stage_progress_updates")
    if not isinstance(stage_updates, dict):
        stage_updates = {}
    stage_update = stage_updates.get(stage_title)
    if not isinstance(stage_update, dict):
        stage_update = {"comment": None, "proof_items": [], "updated_at": None}

    updated_at = dt.datetime.now(dt.timezone.utc).isoformat()
    proof_url = (payload.proof_url or "").strip()
    proof_name = (payload.proof_name or "").strip()
    if proof_url and feedback:
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
                "by": current_admin.username,
                "role": "admin",
                "updated_at": updated_at,
                "proof_url": proof_url,
                "proof_name": proof_name,
            }
        )
        proof_feedback["proof_url"] = proof_url
        proof_feedback["proof_name"] = proof_name
        proof_feedback["thread"] = thread
        proof_feedback["latest_feedback"] = feedback
        proof_feedback["feedback_by"] = current_admin.username
        proof_feedback["updated_at"] = updated_at
        feedback_by_proof[proof_url] = proof_feedback
        stage_update["admin_feedback_by_proof"] = feedback_by_proof
        feedback_thread = thread
    elif feedback:
        feedback_thread = stage_update.get("admin_feedback_thread")
        if not isinstance(feedback_thread, list):
            feedback_thread = []
        feedback_thread.append(
            {
                "feedback": feedback,
                "by": current_admin.username,
                "role": "admin",
                "updated_at": updated_at,
            }
        )
        stage_update["admin_feedback_thread"] = feedback_thread
        stage_update["admin_feedback"] = feedback
        stage_update["admin_feedback_by"] = current_admin.username
        stage_update["admin_feedback_updated_at"] = updated_at
    else:
        feedback_thread = stage_update.get("admin_feedback_thread")
        if not isinstance(feedback_thread, list):
            feedback_thread = []
    if review_status:
        stage_update["review_status"] = review_status
        stage_update["review_status_updated_at"] = updated_at
    stage_update["updated_at"] = updated_at
    stage_updates[stage_title] = stage_update
    project_entry["stage_progress_updates"] = stage_updates
    project_baseline[baseline_key] = project_entry
    settings_row.project_learning_path_baseline = {**project_baseline}
    flag_modified(settings_row, "project_learning_path_baseline")
    db.add(
        ActivityLog(
            user_id=student.id,
            event="admin_stage_feedback",
            meta={
                "repo_name": repo_name,
                "stage_title": stage_title,
                "admin": current_admin.username,
                "review_status": review_status or None,
                "proof_url": proof_url or None,
                "proof_name": proof_name or None,
            },
        )
    )
    db.commit()
    return {
        "username": student.username,
        "repo_name": repo_name,
        "stage_title": stage_title,
        "feedback": feedback,
        "feedback_by": current_admin.username,
        "status": stage_update.get("review_status"),
        "updated_at": updated_at,
        "feedback_thread": feedback_thread,
    }


@router.post("/students/{username}/learning-path/stage-feedback/delete", response_model=AdminStageFeedbackOut)
def delete_stage_feedback(
    username: str,
    payload: AdminStageFeedbackDeleteIn,
    db: Session = Depends(get_db),
    current_admin: AdminAccount = Depends(get_current_admin),
):
    target_username = str(username or "").strip()
    repo_name = str(payload.repo_name or "").strip()
    stage_title = str(payload.stage_title or "").strip()
    updated_at = str(payload.updated_at or "").strip()
    proof_url = str(payload.proof_url or "").strip()
    delete_all = bool(payload.delete_all)
    if not target_username:
        raise HTTPException(status_code=400, detail="Username is required")
    if not repo_name or not stage_title or (not delete_all and not updated_at):
        raise HTTPException(status_code=400, detail="repo_name and stage_title are required, and updated_at is required when delete_all is false")

    student = db.query(User).filter(User.username == target_username).one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    settings_row = db.query(PortfolioSettings).filter(PortfolioSettings.user_id == student.id).one_or_none()
    if not settings_row:
        raise HTTPException(status_code=404, detail="Learning path stage was not found")

    project_baseline = dict(settings_row.project_learning_path_baseline or {})
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

    feedback_thread: list[dict] = []
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
                isinstance(entry, dict)
                and str(entry.get("role") or "").strip().lower() == "admin"
                and str(entry.get("by") or "").strip() == current_admin.username
                and (delete_all or str(entry.get("updated_at") or "").strip() == updated_at)
            )
        ]
        if len(next_thread) == len(thread):
            raise HTTPException(status_code=404, detail="Admin comment was not found")
        if next_thread:
            proof_feedback["thread"] = next_thread
            latest_admin = next(
                (
                    entry for entry in reversed(next_thread)
                    if isinstance(entry, dict) and str(entry.get("role") or "").strip().lower() == "admin"
                ),
                None,
            )
            proof_feedback["latest_feedback"] = latest_admin.get("feedback") if isinstance(latest_admin, dict) else None
            proof_feedback["feedback_by"] = latest_admin.get("by") if isinstance(latest_admin, dict) else None
            proof_feedback["updated_at"] = latest_admin.get("updated_at") if isinstance(latest_admin, dict) else None
            feedback_by_proof[proof_url] = proof_feedback
        else:
            feedback_by_proof.pop(proof_url, None)
        stage_update["admin_feedback_by_proof"] = feedback_by_proof
        feedback_thread = next_thread
    else:
        thread = stage_update.get("admin_feedback_thread")
        if not isinstance(thread, list):
            thread = []
        next_thread = [
            entry for entry in thread
            if not (
                isinstance(entry, dict)
                and str(entry.get("role") or "").strip().lower() == "admin"
                and str(entry.get("by") or "").strip() == current_admin.username
                and (delete_all or str(entry.get("updated_at") or "").strip() == updated_at)
            )
        ]
        if len(next_thread) == len(thread):
            raise HTTPException(status_code=404, detail="Admin comment was not found")
        stage_update["admin_feedback_thread"] = next_thread
        latest_admin = next(
            (
                entry for entry in reversed(next_thread)
                if isinstance(entry, dict) and str(entry.get("role") or "").strip().lower() == "admin"
            ),
            None,
        )
        stage_update["admin_feedback"] = latest_admin.get("feedback") if isinstance(latest_admin, dict) else None
        stage_update["admin_feedback_by"] = latest_admin.get("by") if isinstance(latest_admin, dict) else None
        stage_update["admin_feedback_updated_at"] = latest_admin.get("updated_at") if isinstance(latest_admin, dict) else None
        feedback_thread = next_thread

    stage_updates[stage_title] = stage_update
    project_entry["stage_progress_updates"] = stage_updates
    project_baseline[baseline_key] = project_entry
    settings_row.project_learning_path_baseline = {**project_baseline}
    flag_modified(settings_row, "project_learning_path_baseline")
    db.commit()
    return {
        "username": student.username,
        "repo_name": repo_name,
        "stage_title": stage_title,
        "feedback": stage_update.get("admin_feedback") or "",
        "feedback_by": str(stage_update.get("admin_feedback_by") or ""),
        "updated_at": stage_update.get("admin_feedback_updated_at"),
        "feedback_thread": feedback_thread,
    }


@router.post("/validations", response_model=ProjectValidationOut)
def create_validation(
    payload: ProjectValidationIn,
    db: Session = Depends(get_db),
    current_admin: AdminAccount = Depends(get_current_admin),
):
    student = db.query(User).filter(User.id == payload.student_id).one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    validation = ProjectValidation(
        admin_id=current_admin.id,
        student_id=student.id,
        repo_name=payload.repo_name,
        status=payload.status,
        comment=payload.comment,
    )
    db.add(validation)
    db.commit()
    db.refresh(validation)
    return ProjectValidationOut(
        id=validation.id,
        admin_id=validation.admin_id,
        student_id=validation.student_id,
        repo_name=validation.repo_name,
        status=validation.status,
        comment=validation.comment,
        created_at=str(validation.created_at),
    )


@router.get("/validations", response_model=list[ProjectValidationOut])
def list_all_validations(
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_admin: AdminAccount = Depends(get_current_admin),
):
    query = db.query(ProjectValidation)
    if status:
        query = query.filter(ProjectValidation.status == status)
    rows = query.order_by(ProjectValidation.created_at.desc()).limit(500).all()
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


@router.get("/validations/{student_id}", response_model=list[ProjectValidationOut])
def list_validations(
    student_id: int,
    db: Session = Depends(get_db),
    current_admin: AdminAccount = Depends(get_current_admin),
):
    rows = db.query(ProjectValidation).filter(ProjectValidation.student_id == student_id).order_by(
        ProjectValidation.created_at.desc()
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


@router.post("/portfolio-reviews", response_model=PortfolioReviewOut)
def create_portfolio_review(
    payload: PortfolioReviewIn,
    db: Session = Depends(get_db),
    current_admin: AdminAccount = Depends(get_current_admin),
):
    student = _student_users_query(db).filter(User.id == payload.student_id).one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    row = PortfolioReview(
        admin_id=current_admin.id,
        student_id=payload.student_id,
        status=(payload.status or "needs_work").strip() or "needs_work",
        summary=payload.summary.strip(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return PortfolioReviewOut(
        id=row.id,
        admin_id=row.admin_id,
        student_id=row.student_id,
        status=row.status,
        summary=row.summary,
        created_at=str(row.created_at),
    )


@router.get("/portfolio-reviews/{student_id}", response_model=list[PortfolioReviewOut])
def list_portfolio_reviews(
    student_id: int,
    db: Session = Depends(get_db),
    current_admin: AdminAccount = Depends(get_current_admin),
):
    rows = (
        db.query(PortfolioReview)
        .filter(PortfolioReview.student_id == student_id)
        .order_by(PortfolioReview.created_at.desc())
        .all()
    )
    return [
        PortfolioReviewOut(
            id=row.id,
            admin_id=row.admin_id,
            student_id=row.student_id,
            status=row.status,
            summary=row.summary,
            created_at=str(row.created_at),
        )
        for row in rows
    ]


@router.get("/certificates/pending", response_model=list[CertificateOut])
def list_pending_certificates(
    db: Session = Depends(get_db),
    current_admin: AdminAccount = Depends(get_current_admin),
):
    rows = (
        db.query(CertificateRecord, User)
        .join(User, User.id == CertificateRecord.user_id)
        .filter(CertificateRecord.status == "pending")
        .order_by(CertificateRecord.submitted_at.desc())
        .all()
    )
    thread_maps = {
        row.CertificateRecord.id: _certificate_thread_map(db, row.CertificateRecord.user_id, [row.CertificateRecord.id]).get(row.CertificateRecord.id)
        for row in rows
    }
    return [
        _certificate_payload(row.CertificateRecord, row.User.username, thread_maps.get(row.CertificateRecord.id))
        for row in rows
    ]


@router.post("/certificates/review", response_model=CertificateOut)
def review_certificate(
    payload: CertificateReviewIn,
    db: Session = Depends(get_db),
    current_admin: AdminAccount = Depends(get_current_admin),
):
    row = db.query(CertificateRecord).filter(CertificateRecord.id == payload.certificate_id).one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Certificate not found")
    if payload.status not in {"verified", "rejected", "pending"}:
        raise HTTPException(status_code=400, detail="Invalid certificate status")

    row.status = payload.status
    row.reviewer_note = payload.reviewer_note
    row.reviewer_id = current_admin.id
    row.verified_at = dt.datetime.utcnow() if payload.status == "verified" else None
    db.add(row)
    if str(payload.reviewer_note or "").strip():
        db.add(
            ActivityLog(
                user_id=row.user_id,
                event="certificate_admin_comment",
                meta={
                    "certificate_id": row.id,
                    "comment": str(payload.reviewer_note).strip(),
                    "by": current_admin.username,
                    "role": "admin",
                },
            )
        )
    db.commit()
    db.refresh(row)

    student = db.query(User).filter(User.id == row.user_id).one_or_none()
    return _certificate_payload(row, student.username if student else None, _certificate_thread_map(db, row.user_id, [row.id]).get(row.id))


@router.post("/validations/bulk", response_model=list[ProjectValidationOut])
def create_bulk_validations(
    payload: ValidationBulkIn,
    db: Session = Depends(get_db),
    current_admin: AdminAccount = Depends(get_current_admin),
):
    student = _student_users_query(db).filter(User.id == payload.student_id).one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    if not payload.items:
        raise HTTPException(status_code=400, detail="No validation items provided")

    created: list[ProjectValidation] = []
    for item in payload.items:
        status = (item.status or "pending").lower()
        if status not in {"approved", "pending", "rejected"}:
            continue
        repo_name = (item.repo_name or "").strip()
        if not repo_name:
            continue
        row = ProjectValidation(
            admin_id=current_admin.id,
            student_id=student.id,
            repo_name=repo_name,
            status=status,
            comment=item.comment,
        )
        db.add(row)
        created.append(row)

    if not created:
        raise HTTPException(status_code=400, detail="No valid validation items provided")

    db.commit()
    for row in created:
        db.refresh(row)
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
        for row in created
    ]


@router.post("/certificates/review/bulk", response_model=list[CertificateOut])
def review_certificates_bulk(
    payload: CertificateReviewBulkIn,
    db: Session = Depends(get_db),
    current_admin: AdminAccount = Depends(get_current_admin),
):
    if not payload.items:
        raise HTTPException(status_code=400, detail="No certificate items provided")

    reviewed: list[CertificateOut] = []
    for item in payload.items:
        row = db.query(CertificateRecord).filter(CertificateRecord.id == item.certificate_id).one_or_none()
        if not row:
            continue
        status = (item.status or "pending").lower()
        if status not in {"verified", "rejected", "pending"}:
            continue
        row.status = status
        row.reviewer_note = item.reviewer_note
        row.reviewer_id = current_admin.id
        row.verified_at = dt.datetime.utcnow() if status == "verified" else None
        db.add(row)
        if str(item.reviewer_note or "").strip():
            db.add(
                ActivityLog(
                    user_id=row.user_id,
                    event="certificate_admin_comment",
                    meta={
                        "certificate_id": row.id,
                        "comment": str(item.reviewer_note).strip(),
                        "by": current_admin.username,
                        "role": "admin",
                    },
                )
            )

    db.commit()

    for item in payload.items:
        row = db.query(CertificateRecord).filter(CertificateRecord.id == item.certificate_id).one_or_none()
        if not row:
            continue
        student = db.query(User).filter(User.id == row.user_id).one_or_none()
        reviewed.append(
            CertificateOut(
                **_certificate_payload(row, student.username if student else None, _certificate_thread_map(db, row.user_id, [row.id]).get(row.id))
            )
        )
    return reviewed


@router.post("/certificates/comment", response_model=CertificateOut)
def comment_on_certificate(
    payload: CertificateCommentIn,
    db: Session = Depends(get_db),
    current_admin: AdminAccount = Depends(get_current_admin),
):
    certificate_id = int(payload.certificate_id or 0)
    comment = str(payload.comment or "").strip()
    if certificate_id <= 0 or not comment:
        raise HTTPException(status_code=400, detail="certificate_id and comment are required")

    row = db.query(CertificateRecord).filter(CertificateRecord.id == certificate_id).one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Certificate not found")

    student = db.query(User).filter(User.id == row.user_id).one_or_none()
    db.add(
        ActivityLog(
            user_id=row.user_id,
            event="certificate_admin_comment",
            meta={
                "certificate_id": row.id,
                "comment": comment,
                "by": current_admin.username,
                "role": "admin",
            },
        )
    )
    db.commit()
    return _certificate_payload(row, student.username if student else None, _certificate_thread_map(db, row.user_id, [row.id]).get(row.id))


@router.post("/certificates/comment-delete", response_model=CertificateOut)
def delete_certificate_comment(
    payload: CertificateCommentDeleteIn,
    db: Session = Depends(get_db),
    current_admin: AdminAccount = Depends(get_current_admin),
):
    certificate_id = int(payload.certificate_id or 0)
    updated_at = str(payload.updated_at or "").strip()
    delete_all = bool(payload.delete_all)
    if certificate_id <= 0 or (not delete_all and not updated_at):
        raise HTTPException(status_code=400, detail="certificate_id is required, and updated_at is required when delete_all is false")

    row = db.query(CertificateRecord).filter(CertificateRecord.id == certificate_id).one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Certificate not found")

    matching_logs = (
        db.query(ActivityLog)
        .filter(
            ActivityLog.user_id == row.user_id,
            ActivityLog.event == "certificate_admin_comment",
        )
        .order_by(ActivityLog.created_at.asc(), ActivityLog.id.asc())
        .all()
    )
    target_logs = [
        log for log in matching_logs
        if int((log.meta or {}).get("certificate_id") or 0) == certificate_id
        and str((log.meta or {}).get("role") or "").strip().lower() == "admin"
        and str((log.meta or {}).get("by") or "").strip() == current_admin.username
        and (delete_all or str(log.created_at or "").strip() == updated_at)
    ]
    if not target_logs:
        raise HTTPException(status_code=404, detail="Admin comment was not found")

    student = db.query(User).filter(User.id == row.user_id).one_or_none()
    for target_log in target_logs:
        db.delete(target_log)
    db.commit()
    return _certificate_payload(row, student.username if student else None, _certificate_thread_map(db, row.user_id, [row.id]).get(row.id))


@router.get("/export/students.csv")
def export_students_csv(
    db: Session = Depends(get_db),
    current_admin: AdminAccount = Depends(get_current_admin),
):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id",
        "username",
        "display_name",
        "program",
        "year_level",
        "xp",
        "level",
        "repo_count",
        "last_seen",
    ])

    for student in _student_users_query(db).all():
        repos = db.query(Repo).filter(Repo.user_id == student.id).all()
        xp = int(student.bonus_xp or 0)
        for repo in repos:
            xp += int(repo.commit_count or 0) * 2
            xp += 50
            xp += int(repo.stars or 0)
        level = level_from_xp(xp)
        writer.writerow([
            student.id,
            student.username,
            student.display_name or "",
            student.program or "",
            student.year_level or "",
            xp,
            level,
            len(repos),
            str(student.last_seen) if student.last_seen else "",
        ])

    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=students_report.csv"},
    )


@router.get("/research/analytics", response_model=ResearchAnalyticsOut)
def get_research_analytics(
    db: Session = Depends(get_db),
    current_admin: AdminAccount = Depends(get_current_admin),
):
    students = _student_users_query(db).all()
    student_ids = [student.id for student in students]
    now = _now_utc()
    since = now - dt.timedelta(days=7)

    actions = (
        db.query(RecommendationAction).filter(RecommendationAction.user_id.in_(student_ids)).all()
        if student_ids
        else []
    )
    accepted = sum(1 for row in actions if row.action in {"accepted", "completed"})
    acceptance_rate = int(round((accepted / len(actions)) * 100)) if actions else 0
    rating_rows = [row for row in actions if row.rating is not None]
    relevant_rows = [row for row in rating_rows if int(row.rating or 0) >= 4]
    relevance_rate = int(round((len(relevant_rows) / len(rating_rows)) * 100)) if rating_rows else 0

    weekly_login_events = db.query(ActivityLog).filter(
        ActivityLog.user_id.in_(student_ids) if student_ids else False,
        ActivityLog.event.in_(["login", "heartbeat"]),
        ActivityLog.created_at >= since,
    ).count()
    weekly_profile_updates = db.query(ActivityLog).filter(
        ActivityLog.user_id.in_(student_ids) if student_ids else False,
        ActivityLog.event == "profile_update",
        ActivityLog.created_at >= since,
    ).count()

    active_students_14d = sum(
        1
        for student in students
        if (elapsed := _elapsed_since(student.last_seen, now)) is not None
        and elapsed <= dt.timedelta(days=14)
    )

    student_count = max(1, len(students))
    return ResearchAnalyticsOut(
        recommendation_acceptance_rate=acceptance_rate,
        recommendation_ratings_total=len(rating_rows),
        recommendation_relevance_rate=relevance_rate,
        weekly_login_frequency=round(weekly_login_events / student_count, 2),
        weekly_portfolio_update_frequency=round(weekly_profile_updates / student_count, 2),
        active_students_14d=active_students_14d,
    )
    last_logout_at = (
        db.query(func.max(ActivityLog.created_at))
        .filter(ActivityLog.user_id == student.id, ActivityLog.event == "logout")
        .scalar()
    )
