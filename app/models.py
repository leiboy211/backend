from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, JSON, UniqueConstraint, func
from sqlalchemy.orm import relationship

from app.db import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    github_id = Column(String(64), unique=True, index=True, nullable=False)
    username = Column(String(64), unique=True, index=True, nullable=False)
    avatar_url = Column(Text, nullable=False)
    display_name = Column(String(120), nullable=True)
    bio = Column(Text, nullable=True)
    student_id = Column(String(64), nullable=True)
    program = Column(String(64), nullable=True)
    year_level = Column(String(32), nullable=True)
    career_interest = Column(String(160), nullable=True)
    preferred_learning_style = Column(String(80), nullable=True)
    target_role = Column(String(160), nullable=True)
    target_certifications = Column(JSON, default=list)
    github_token = Column(Text, nullable=True)
    freecodecamp_username = Column(String(120), nullable=True)
    bonus_xp = Column(Integer, default=0)
    last_cert_sync_at = Column(DateTime(timezone=True), nullable=True)
    role = Column(String(20), default="student")
    last_seen = Column(DateTime(timezone=True), nullable=True)
    is_verified = Column(Boolean, default=False)
    verified_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    repos = relationship("Repo", back_populates="user", cascade="all, delete-orphan")
    practice_dimensions = relationship(
        "PracticeDimension", back_populates="user", cascade="all, delete-orphan"
    )
    career_suggestions = relationship(
        "CareerSuggestion", back_populates="user", cascade="all, delete-orphan"
    )
    badges = relationship("Badge", back_populates="user", cascade="all, delete-orphan")
    portfolio_settings = relationship(
        "PortfolioSettings", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )


class Repo(Base):
    __tablename__ = "repos"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    language = Column(String(64), nullable=True)
    languages = Column(JSON, default=list)
    language_bytes = Column(JSON, default=dict)
    stars = Column(Integer, default=0)
    topics = Column(JSON, default=list)
    code_signals = Column(JSON, default=dict)
    last_push = Column(Text, nullable=True)
    commit_count = Column(Integer, default=0)

    user = relationship("User", back_populates="repos")


class PracticeDimension(Base):
    __tablename__ = "practice_dimensions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    label = Column(String(120), nullable=False)
    confidence = Column(Integer, nullable=False)
    evidence = Column(JSON, default=list)

    user = relationship("User", back_populates="practice_dimensions")


class CareerSuggestion(Base):
    __tablename__ = "career_suggestions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String(160), nullable=False)
    confidence = Column(Integer, nullable=False)
    reasoning = Column(Text, nullable=False)

    user = relationship("User", back_populates="career_suggestions")


class Badge(Base):
    __tablename__ = "badges"
    __table_args__ = (
        UniqueConstraint("user_id", "label", name="uq_badges_user_label"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    label = Column(String(120), nullable=False)
    description = Column(Text, nullable=False)
    criteria = Column(Text, nullable=False)
    rarity = Column(String(20), nullable=False)
    achieved = Column(Boolean, default=False)
    claimed = Column(Boolean, default=False)

    user = relationship("User", back_populates="badges")


class PortfolioSettings(Base):
    __tablename__ = "portfolio_settings"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    theme = Column(String(32), default="aurora")
    theme_light = Column(String(32), default="aurora")
    theme_dark = Column(String(32), default="aurora")
    section_order = Column(JSON, default=list)
    show_sections = Column(JSON, default=lambda: {"badges": True, "repos": True, "preview_dark": False})
    featured_repos = Column(JSON, default=list)
    featured_badges = Column(JSON, default=list)
    social_links = Column(JSON, default=dict)
    bio = Column(Text, nullable=True)
    cover_image = Column(Text, nullable=True)
    is_public = Column(Boolean, default=True)
    learning_path_baseline = Column(JSON, default=list)
    project_learning_path_baseline = Column(JSON, default=dict)

    user = relationship("User", back_populates="portfolio_settings")


class AdminNote(Base):
    __tablename__ = "admin_notes"

    id = Column(Integer, primary_key=True, index=True)
    admin_id = Column(Integer, ForeignKey("admin_accounts.id"), nullable=False)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    note = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ProjectValidation(Base):
    __tablename__ = "project_validations"

    id = Column(Integer, primary_key=True, index=True)
    admin_id = Column(Integer, ForeignKey("admin_accounts.id"), nullable=False)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    repo_name = Column(String(200), nullable=False)
    status = Column(String(20), default="pending")
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class PortfolioReview(Base):
    __tablename__ = "portfolio_reviews"

    id = Column(Integer, primary_key=True, index=True)
    admin_id = Column(Integer, ForeignKey("admin_accounts.id"), nullable=False)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    status = Column(String(30), default="needs_work")
    summary = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AdminAccount(Base):
    __tablename__ = "admin_accounts"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(64), unique=True, index=True, nullable=False)
    password_hash = Column(Text, nullable=False)
    password_salt = Column(String(64), nullable=False)
    role = Column(String(20), default="admin")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ActivityLog(Base):
    __tablename__ = "activity_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    event = Column(String(64), nullable=False)
    meta = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class EngagementCommit(Base):
    __tablename__ = "engagement_commits"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    week_start = Column(DateTime(timezone=True), nullable=False)
    commit_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class LearningProgress(Base):
    __tablename__ = "learning_progress"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    learning_step = Column(Text, nullable=False)
    status = Column(String(20), default="todo")
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class LearningPath(Base):
    """Normalized, queryable learning path header per student/repository."""

    __tablename__ = "learning_paths"
    __table_args__ = (
        UniqueConstraint("user_id", "repo_name", "path_level", name="uq_learning_paths_user_repo_level"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    repo_name = Column(String(200), nullable=False, index=True)
    path_level = Column(Integer, default=1, nullable=False)
    status = Column(String(20), default="active", nullable=False)
    progress_percent = Column(Integer, default=0, nullable=False)
    personalization_key = Column(String(128), nullable=True)
    source_profile = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class LearningPathStage(Base):
    """One concrete, ordered skill stage belonging to a normalized path."""

    __tablename__ = "learning_path_stages"
    __table_args__ = (
        UniqueConstraint("learning_path_id", "stage_index", name="uq_learning_path_stage_order"),
    )

    id = Column(Integer, primary_key=True, index=True)
    learning_path_id = Column(Integer, ForeignKey("learning_paths.id"), nullable=False, index=True)
    stage_index = Column(Integer, nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    stage_type = Column(String(30), default="Skill", nullable=False)
    tag = Column(String(120), nullable=True)
    difficulty = Column(String(30), default="Beginner", nullable=False)
    reward_xp = Column(Integer, default=0, nullable=False)
    resources = Column(JSON, default=dict)
    evidence = Column(JSON, default=list)
    status = Column(String(20), default="todo", nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class StageProgressUpdate(Base):
    """Student proof/history for one normalized skill stage."""

    __tablename__ = "stage_progress_updates"

    id = Column(Integer, primary_key=True, index=True)
    learning_path_stage_id = Column(Integer, ForeignKey("learning_path_stages.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    comment = Column(Text, nullable=True)
    proof_items = Column(JSON, default=list)
    review_status = Column(String(20), default="pending", nullable=False)
    admin_feedback = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class XpHistory(Base):
    __tablename__ = "xp_history"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    week_start = Column(DateTime(timezone=True), nullable=False)
    xp_gained = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class LoginActivity(Base):
    __tablename__ = "login_activity"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    login_timestamp = Column(DateTime(timezone=True), nullable=False)
    login_date = Column(String(10), nullable=False)
    login_hour = Column(Integer, nullable=False)
    ip_address = Column(String(64), nullable=True)
    device = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class CertificateRecord(Base):
    __tablename__ = "certificate_records"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    provider = Column(String(160), nullable=False)
    proof_type = Column(String(40), nullable=True)
    certificate_url = Column(Text, nullable=False)
    certificate_page_url = Column(Text, nullable=True)
    student_note = Column(Text, nullable=True)
    suggestion_track_id = Column(String(160), nullable=True, index=True)
    suggestion_module_url = Column(Text, nullable=True)
    completion_locked = Column(Boolean, default=False)
    completion_reward_xp = Column(Integer, nullable=True)
    rewarded_at = Column(DateTime(timezone=True), nullable=True)
    hidden_from_student = Column(Boolean, default=False)
    status = Column(String(20), default="pending")
    reviewer_id = Column(Integer, ForeignKey("admin_accounts.id"), nullable=True)
    reviewer_note = Column(Text, nullable=True)
    submitted_at = Column(DateTime(timezone=True), server_default=func.now())
    verified_at = Column(DateTime(timezone=True), nullable=True)


class FccModuleProgress(Base):
    __tablename__ = "fcc_module_progress"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    module_key = Column(String(120), nullable=False, index=True)
    module_title = Column(String(255), nullable=False)
    status = Column(String(20), default="not_started")
    progress_percent = Column(Integer, default=0)
    notes = Column(Text, nullable=True)
    certificate_url = Column(Text, nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class InterventionPlan(Base):
    __tablename__ = "intervention_plans"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    admin_id = Column(Integer, ForeignKey("admin_accounts.id"), nullable=False)
    title = Column(String(255), nullable=False)
    action_plan = Column(Text, nullable=False)
    priority = Column(String(20), default="Medium")
    target_date = Column(String(20), nullable=True)
    status = Column(String(20), default="open")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class DailyQuestClaim(Base):
    __tablename__ = "daily_quest_claims"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    quest_key = Column(String(80), nullable=False)
    quest_date = Column(String(10), nullable=False, index=True)
    reward_xp = Column(Integer, default=0)
    claimed_at = Column(DateTime(timezone=True), server_default=func.now())


class WeeklyChallengeClaim(Base):
    __tablename__ = "weekly_challenge_claims"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    challenge_key = Column(String(80), nullable=False)
    week_start = Column(String(10), nullable=False, index=True)
    reward_xp = Column(Integer, default=0)
    claimed_at = Column(DateTime(timezone=True), server_default=func.now())


class RecommendationAction(Base):
    __tablename__ = "recommendation_actions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    dimension_key = Column(String(120), nullable=True)
    module_title = Column(String(255), nullable=False)
    module_url = Column(Text, nullable=False)
    action = Column(String(20), nullable=False)
    rating = Column(Integer, nullable=True)
    feedback = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class SusSurveyResponse(Base):
    __tablename__ = "sus_survey_responses"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    score = Column(Integer, nullable=False)
    feedback = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class StudentGoal(Base):
    __tablename__ = "student_goals"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    target_value = Column(Integer, nullable=True)
    current_value = Column(Integer, default=0)
    unit = Column(String(64), nullable=True)
    status = Column(String(20), default="active")
    target_date = Column(String(20), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
