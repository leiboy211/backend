from pydantic import BaseModel, Field


class PracticeDimensionOut(BaseModel):
    label: str
    confidence: int = Field(ge=0, le=100)
    evidence: list[str]


class CareerSuggestionOut(BaseModel):
    title: str
    confidence: int = Field(ge=0, le=100)
    reasoning: str


class SkillDomainOut(BaseModel):
    dimension_key: str
    domain: str
    description: str
    score_percent: int = Field(ge=0, le=100)
    level: str
    evidence: list[str] = Field(default_factory=list)


class WeeklyCommitOut(BaseModel):
    week_start: str
    commit_count: int


class FrequencySummaryOut(BaseModel):
    total_commits: int
    repo_count: int
    active_repos_30d: int
    weekly_commits: list[WeeklyCommitOut] = Field(default_factory=list)
    weekly_commit_average: float
    streak_days: int


class BadgeOut(BaseModel):
    label: str
    description: str
    criteria: str
    rarity: str
    achieved: bool
    claimed: bool
    reward_xp: int | None = None
    medal_tier: str | None = None
    medal_icon: str | None = None
    category: str | None = None
    category_icon: str | None = None
    icon: str | None = None
    target: int | None = None


class RepoOut(BaseModel):
    name: str
    description: str | None = None
    language: str | None = None
    languages: list[str] | None = None
    language_bytes: dict[str, int] | None = None
    code_signals: dict | None = None
    stars: int
    last_push: str | None = None
    commit_count: int


class UserOut(BaseModel):
    username: str
    display_name: str | None = None
    bio: str | None = None
    student_id: str | None = None
    program: str | None = None
    year_level: str | None = None
    career_interest: str | None = None
    preferred_learning_style: str | None = None
    target_role: str | None = None
    target_certifications: list[str] = Field(default_factory=list)
    avatar_url: str
    level: int
    xp: int
    next_level_xp: int
    streak_days: int
    portfolio_completeness: int = 0
    has_recommendation_action: bool = False
    is_verified: bool = False
    verified_at: str | None = None


class UserResponse(BaseModel):
    profile: UserOut
    practice_dimensions: list[PracticeDimensionOut]
    career_suggestions: list[CareerSuggestionOut]
    skill_domains: list[SkillDomainOut] = Field(default_factory=list)
    focus_domain: SkillDomainOut | None = None
    frequency: FrequencySummaryOut | None = None
    badges: list[BadgeOut]
    repos: list[RepoOut]


class PortfolioSettingsIn(BaseModel):
    theme: str | None = None
    theme_light: str | None = None
    theme_dark: str | None = None
    section_order: list[str] | None = None
    show_sections: dict | None = None
    featured_repos: list[str] | None = None
    featured_badges: list[str] | None = None
    social_links: dict | None = None
    bio: str | None = None
    cover_image: str | None = None
    is_public: bool | None = None
    display_name: str | None = None


class PortfolioResponse(BaseModel):
    profile: UserOut
    practice_dimensions: list[PracticeDimensionOut]
    career_suggestions: list[CareerSuggestionOut]
    skill_domains: list[SkillDomainOut] = Field(default_factory=list)
    focus_domain: SkillDomainOut | None = None
    frequency: FrequencySummaryOut | None = None
    badges: list[BadgeOut]
    repos: list[RepoOut]
    settings: dict


class RegistrationIn(BaseModel):
    display_name: str | None = None
    bio: str | None = None
    student_id: str | None = None
    program: str | None = None
    year_level: str | None = None
    career_interest: str | None = None
    preferred_learning_style: str | None = None
    target_role: str | None = None
    target_certifications: list[str] | None = None


class LeaderboardBadgeOut(BaseModel):
    label: str
    rarity: str
    medal_icon: str | None = None
    achieved: bool = False
    claimed: bool = False


class LeaderboardEntryOut(BaseModel):
    id: int
    username: str
    avatar_url: str
    program: str | None = None
    year_level: str | None = None
    level: int
    xp: int
    runway_xp: int
    runway_remaining_xp: int
    delta: str
    badge_count: int = 0
    badge_stack: list[LeaderboardBadgeOut] = Field(default_factory=list)


class AdminStudentSummary(BaseModel):
    id: int
    username: str
    display_name: str | None = None
    avatar_url: str
    level: int
    xp: int
    repo_count: int
    badges_claimed: int
    online: bool
    last_seen: str | None = None
    program: str | None = None
    year_level: str | None = None
    is_verified: bool = False
    verified_at: str | None = None


class AdminStudentRecommendationActionOut(BaseModel):
    id: int
    dimension_key: str | None = None
    module_title: str
    module_url: str
    action: str
    rating: int | None = None
    feedback: str | None = None
    created_at: str


class AdminStudentActivityItemOut(BaseModel):
    id: int
    event: str
    meta: dict = Field(default_factory=dict)
    created_at: str


class AdminStudentDetailProfileOut(BaseModel):
    bio: str | None = None
    student_id: str | None = None
    career_interest: str | None = None
    preferred_learning_style: str | None = None
    target_role: str | None = None
    target_certifications: list[str] = Field(default_factory=list)
    email: str | None = None
    linkedin: str | None = None
    phone: str | None = None
    tech_stack: list[str] = Field(default_factory=list)
    education_history: list[dict] = Field(default_factory=list)
    job_experience: list[dict] = Field(default_factory=list)
    profile_image: str | None = None
    created_at: str | None = None


class AdminStudentDetailOverviewOut(BaseModel):
    total_commits: int
    total_stars: int
    repo_count: int
    badges_claimed: int
    certificates_total: int
    certificates_verified: int
    recommendation_actions_total: int
    recommendation_acceptance_rate: int
    recommendation_relevance_rate: int
    portfolio_completeness: int
    days_since_last_seen: int | None = None


class AdminStudentDetailOut(BaseModel):
    student: AdminStudentSummary
    profile: AdminStudentDetailProfileOut
    overview: AdminStudentDetailOverviewOut
    top_repos: list[RepoOut] = Field(default_factory=list)
    practice_dimensions: list[PracticeDimensionOut] = Field(default_factory=list)
    career_suggestions: list[CareerSuggestionOut] = Field(default_factory=list)
    recent_recommendations: list[AdminStudentRecommendationActionOut] = Field(default_factory=list)
    recent_activity: list[AdminStudentActivityItemOut] = Field(default_factory=list)
    fcc_progress_summary: "FccModuleProgressSummaryOut | None" = None
    fcc_progress: list["FccModuleProgressOut"] = Field(default_factory=list)
    certificates: list["CertificateOut"] = Field(default_factory=list)
    validations: list["ProjectValidationOut"] = Field(default_factory=list)
    notes: list["AdminNoteOut"] = Field(default_factory=list)
    reviews: list["PortfolioReviewOut"] = Field(default_factory=list)


class AdminNoteIn(BaseModel):
    student_id: int
    note: str


class AdminNoteOut(BaseModel):
    id: int
    admin_id: int
    student_id: int
    note: str
    created_at: str


class ProjectValidationIn(BaseModel):
    student_id: int
    repo_name: str
    status: str
    comment: str | None = None


class ProjectValidationOut(BaseModel):
    id: int
    admin_id: int
    student_id: int
    repo_name: str
    status: str
    comment: str | None = None
    created_at: str


class PortfolioReviewIn(BaseModel):
    student_id: int
    status: str = "needs_work"
    summary: str


class PortfolioReviewOut(BaseModel):
    id: int
    admin_id: int
    student_id: int
    status: str
    summary: str
    created_at: str


class StudentVerifyIn(BaseModel):
    student_id: int
    is_verified: bool


class StudentVerifyOut(BaseModel):
    student_id: int
    is_verified: bool
    verified_at: str | None = None


class AdminAnalyticsOut(BaseModel):
    total_students: int
    total_repos: int
    avg_xp: int
    avg_level: int
    pending_validations: int
    adoption_users: int = 0
    adoption_total_users: int = 0
    adoption_rate: int = 0


class AdminAnalyticsDay(BaseModel):
    date: str
    logins: int
    profile_updates: int
    recomputes: int
    learning_path_views: int


class AdminAnalyticsLabel(BaseModel):
    label: str
    count: int


class AdminDeepAnalyticsOut(BaseModel):
    days: list[AdminAnalyticsDay]
    top_languages: list[AdminAnalyticsLabel]
    total_events: int


class AdminLoginIn(BaseModel):
    username: str
    password: str


class AdminLoginOut(BaseModel):
    username: str
    token: str
    role: str


class LearningStepResourceItemOut(BaseModel):
    name: str
    url: str | None = None


class LearningStepResourcesOut(BaseModel):
    courses: list[LearningStepResourceItemOut] = Field(default_factory=list)
    tools: list[LearningStepResourceItemOut] = Field(default_factory=list)
    documentation: list[LearningStepResourceItemOut] = Field(default_factory=list)


class LearningStepOnRejectOut(BaseModel):
    title: str
    description: str


class LearningStepOnCompleteOut(BaseModel):
    next_step: str
    next_focus: str


class LearningStepAdaptiveOut(BaseModel):
    on_reject: LearningStepOnRejectOut
    on_complete: LearningStepOnCompleteOut


class LearningPathStepOut(BaseModel):
    title: str
    description: str | None = None
    reason: str
    type: str | None = None
    tag: str | None = None
    dimension_key: str | None = None
    evidence: list[str] | None = None
    difficulty: str | None = None
    reward_xp: int | None = None
    estimated_xp: int | None = None
    tags: list[str] | None = None
    resources: LearningStepResourcesOut | None = None
    adaptive: LearningStepAdaptiveOut | None = None
    ai_explanation: str | None = None
    progression_logic: str | None = None
    status: str | None = None
    priority: str | None = None
    dimension: str | None = None
    competency_level: str | None = None
    progression_step: int | None = None


class CompetencyDimensionOut(BaseModel):
    dimension_key: str
    dimension: str
    description: str
    score_percent: int = Field(ge=0, le=100)
    level: str
    evidence: list[str]


class SkillGapOut(BaseModel):
    dimension_key: str
    dimension: str
    score_percent: int = Field(ge=0, le=100)
    current_level: str
    target_level: str
    priority: str
    gap_summary: str


class LearningPathResponse(BaseModel):
    username: str
    steps: list[LearningPathStepOut]
    progress_percent: int | None = None
    competency_levels: list[CompetencyDimensionOut] = Field(default_factory=list)
    skill_gaps: list[SkillGapOut] = Field(default_factory=list)


class ProjectLearningPathOut(BaseModel):
    repo_name: str
    steps: list[LearningPathStepOut]
    progress_percent: int | None = None
    path_level: int = 1
    repo_completed: bool = False
    repo_completed_at: str | None = None
    stage_status_overrides: dict[str, str] = Field(default_factory=dict)
    stage_checks: dict[str, list[bool]] = Field(default_factory=dict)
    stage_proof_counts: dict[str, int] = Field(default_factory=dict)
    stage_progress_updates: dict[str, dict] = Field(default_factory=dict)


class ProjectLearningPathResponse(BaseModel):
    username: str
    projects: list[ProjectLearningPathOut]


class CertificateSuggestionOut(BaseModel):
    id: str
    title: str
    provider: str
    url: str
    reward_xp: int
    completed: bool = False
    locked: bool = False
    claimed_reward_xp: int = 0
    provider_aliases: list[str] = Field(default_factory=list)
    match_tokens: list[str] = Field(default_factory=list)
    groups: list[str] = Field(default_factory=list)
    reasoning: str | None = None


class CertificateSuggestionListOut(BaseModel):
    username: str
    items: list[CertificateSuggestionOut] = Field(default_factory=list)


class ProjectStageStatusIn(BaseModel):
    repo_name: str
    stage_title: str
    status: str
    checks: list[bool] | None = None
    proof_count: int | None = None


class ProjectStageStatusOut(BaseModel):
    repo_name: str
    stage_title: str
    status: str
    checks: list[bool] | None = None
    proof_count: int | None = None


class ProjectStageProgressUpdateIn(BaseModel):
    repo_name: str
    stage_title: str
    comment: str | None = None
    proof_items: list[dict] = Field(default_factory=list)
    final_proof_items: list[dict] = Field(default_factory=list)


class ProjectStageFeedbackReplyIn(BaseModel):
    repo_name: str
    stage_title: str
    feedback: str
    proof_url: str | None = None
    proof_name: str | None = None


class ProjectStageFeedbackReplyDeleteIn(BaseModel):
    repo_name: str
    stage_title: str
    updated_at: str | None = None
    proof_url: str | None = None
    delete_all: bool = False


class ProjectStageProofDeleteIn(BaseModel):
    repo_name: str
    stage_title: str
    proof_url: str


class ProjectStageProgressDeleteIn(BaseModel):
    repo_name: str
    stage_title: str
    entry_id: str | None = None
    proof_url: str | None = None
    clear_comment: bool = False
    delete_entry: bool = False


class ProjectStageProgressEntryOut(BaseModel):
    entry_id: str
    comment: str | None = None
    proof_items: list[dict] = Field(default_factory=list)
    updated_at: str | None = None


class ProjectStageProgressUpdateOut(BaseModel):
    repo_name: str
    stage_title: str
    comment: str | None = None
    proof_items: list[dict] = Field(default_factory=list)
    final_proof_items: list[dict] = Field(default_factory=list)
    review_status: str | None = None
    review_status_updated_at: str | None = None
    updated_at: str | None = None
    progress_entries: list[ProjectStageProgressEntryOut] = Field(default_factory=list)
    admin_feedback: str | None = None
    admin_feedback_by: str | None = None
    admin_feedback_updated_at: str | None = None
    admin_feedback_thread: list[dict] = Field(default_factory=list)
    admin_feedback_by_proof: dict[str, dict] = Field(default_factory=dict)


class ProjectLearningPathClaimIn(BaseModel):
    repo_name: str


class ProjectLearningPathClaimOut(BaseModel):
    repo_name: str
    claimed_xp: int
    next_path_level: int | None = None
    repo_completed: bool = False
    claimed_at: str


class ProjectStageResetIn(BaseModel):
    repo_name: str
    stage_titles: list[str] = Field(default_factory=list)


class ProjectStageResetOut(BaseModel):
    repo_name: str
    stage_titles: list[str] = Field(default_factory=list)


class AdminStageFeedbackIn(BaseModel):
    repo_name: str
    stage_title: str
    feedback: str | None = None
    proof_url: str | None = None
    proof_name: str | None = None
    status: str | None = None


class AdminStageFeedbackDeleteIn(BaseModel):
    repo_name: str
    stage_title: str
    updated_at: str | None = None
    proof_url: str | None = None
    delete_all: bool = False


class AdminStageFeedbackOut(BaseModel):
    username: str
    repo_name: str
    stage_title: str
    feedback: str
    feedback_by: str
    status: str | None = None
    updated_at: str | None = None
    feedback_thread: list[dict] = Field(default_factory=list)


class EngagementCommitOut(BaseModel):
    week_start: str
    commit_count: int


class XpHistoryOut(BaseModel):
    week_start: str
    xp_gained: int


class LearningProgressOut(BaseModel):
    learning_step: str
    status: str
    completed_at: str | None = None


class EngagementAnalyticsOut(BaseModel):
    weekly_commits: list[EngagementCommitOut]
    xp_growth: list[XpHistoryOut]
    learning_progress: list[LearningProgressOut]
    engagement_score: int


class ActivityTimelineOut(BaseModel):
    date: str
    event: str


class LoginTrendPoint(BaseModel):
    date: str
    count: int


class PeakHourPoint(BaseModel):
    hour: int
    count: int


class WeeklyActivePoint(BaseModel):
    week_start: str
    active_users: int


class LoginStreakOut(BaseModel):
    user_id: int | None = None
    username: str | None = None
    current_streak: int


class LoginGroupCountOut(BaseModel):
    label: str
    count: int


class LoginActivityOut(BaseModel):
    daily_counts: list[LoginTrendPoint]
    peak_hours: list[PeakHourPoint]
    weekly_active: list[WeeklyActivePoint]
    streak: LoginStreakOut


class RecentLoginOut(BaseModel):
    login_timestamp: str
    device: str | None = None


class LoginActivityTrendsOut(BaseModel):
    daily_counts: list[LoginTrendPoint]
    peak_hours: list[PeakHourPoint]
    weekly_active: list[WeeklyActivePoint]
    streaks: list[LoginStreakOut]
    program_logins: list[LoginGroupCountOut] = Field(default_factory=list)
    year_level_logins: list[LoginGroupCountOut] = Field(default_factory=list)


class LiveLoginPoint(BaseModel):
    time: str
    count: int


class LoginLiveOut(BaseModel):
    window_hours: int
    bucket_minutes: int
    points: list[LiveLoginPoint]


class LoginActivityDetailOut(LoginActivityOut):
    recent_logins: list[RecentLoginOut]


class CurriculumSubjectOut(BaseModel):
    code: str
    title: str
    program: str
    year_level: int
    focus_dimension_key: str
    focus_dimension: str
    coverage_percent: int = Field(ge=0, le=100)
    status: str
    recommended_module: str


class SkillHeatmapCellOut(BaseModel):
    subject_code: str
    dimension_key: str
    dimension: str
    score_percent: int = Field(ge=0, le=100)
    band: str


class CurriculumMapOut(BaseModel):
    username: str
    subjects: list[CurriculumSubjectOut] = Field(default_factory=list)
    heatmap: list[SkillHeatmapCellOut] = Field(default_factory=list)


class RuleRecommendationOut(BaseModel):
    dimension_key: str
    dimension: str
    reason: str
    module_title: str
    module_url: str
    certificate_hint: str
    acted: bool = False


class PeerRecommendationOut(BaseModel):
    title: str
    description: str
    module_url: str
    dimension_key: str | None = None
    similar_students_count: int = 0


class RuleRecommendationListOut(BaseModel):
    username: str
    items: list[RuleRecommendationOut] = Field(default_factory=list)
    peer_recommendations: list[PeerRecommendationOut] = Field(default_factory=list)


class WeeklyDigestOut(BaseModel):
    username: str
    week_start: str
    commits: int
    xp_gained: int
    completed_steps: int
    active_days: int
    summary: str


class CertificateSubmitIn(BaseModel):
    title: str
    provider: str
    proof_type: str | None = None
    certificate_url: str
    certificate_page_url: str | None = None
    student_note: str | None = None
    suggestion_track_id: str | None = None
    suggestion_module_url: str | None = None
    final_completion: bool = False
    reward_xp: int | None = Field(default=None, ge=0)


class AutoStageCertificateIn(BaseModel):
    repo_name: str
    stage_title: str
    title: str
    provider: str
    proof_type: str | None = None
    certificate_url: str
    certificate_page_url: str | None = None
    student_note: str | None = None


class CertificateReviewIn(BaseModel):
    certificate_id: int
    status: str
    reviewer_note: str | None = None


class CertificateCommentIn(BaseModel):
    certificate_id: int
    comment: str


class CertificateCommentDeleteIn(BaseModel):
    certificate_id: int
    updated_at: str | None = None
    delete_all: bool = False


class CertificateStudentCommentDeleteIn(BaseModel):
    certificate_id: int
    updated_at: str | None = None
    delete_all: bool = False


class CertificateProgressDeleteIn(BaseModel):
    certificate_id: int
    clear_comment: bool = False
    delete_proof: bool = False


class CertificateRewardClaimIn(BaseModel):
    certificate_id: int


class CertificateThreadEntryOut(BaseModel):
    comment: str
    by: str
    role: str
    updated_at: str | None = None


class CertificateOut(BaseModel):
    id: int
    user_id: int
    username: str | None = None
    title: str
    provider: str
    proof_type: str | None = None
    certificate_url: str
    certificate_page_url: str | None = None
    student_note: str | None = None
    suggestion_track_id: str | None = None
    suggestion_module_url: str | None = None
    completion_locked: bool = False
    completion_reward_xp: int | None = None
    rewarded_at: str | None = None
    hidden_from_student: bool = False
    status: str
    reviewer_note: str | None = None
    submitted_at: str
    verified_at: str | None = None
    comment_thread: list[CertificateThreadEntryOut] = Field(default_factory=list)
    latest_admin_comment_at: str | None = None
    latest_student_reply_at: str | None = None


class FccModuleProgressIn(BaseModel):
    module_title: str
    status: str
    progress_percent: int = Field(ge=0, le=100)
    notes: str | None = None
    certificate_url: str | None = None


class FccModuleProgressOut(BaseModel):
    id: int
    user_id: int
    module_key: str
    module_title: str
    status: str
    progress_percent: int = Field(ge=0, le=100)
    notes: str | None = None
    certificate_url: str | None = None
    completed_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class FccModuleProgressSummaryOut(BaseModel):
    overall_progress_percent: int = Field(ge=0, le=100)
    modules_started: int
    modules_completed: int
    total_modules: int
    last_updated_at: str | None = None


class FccModuleProgressListOut(BaseModel):
    summary: FccModuleProgressSummaryOut
    items: list[FccModuleProgressOut] = Field(default_factory=list)


class StudentGoalIn(BaseModel):
    title: str
    target_value: int | None = Field(default=None, ge=0)
    current_value: int | None = Field(default=0, ge=0)
    unit: str | None = None
    status: str = "active"
    target_date: str | None = None
    notes: str | None = None


class StudentGoalUpdateIn(BaseModel):
    title: str | None = None
    target_value: int | None = Field(default=None, ge=0)
    current_value: int | None = Field(default=None, ge=0)
    unit: str | None = None
    status: str | None = None
    target_date: str | None = None
    notes: str | None = None


class StudentGoalOut(BaseModel):
    id: int
    user_id: int
    title: str
    target_value: int | None = None
    current_value: int
    unit: str | None = None
    status: str
    target_date: str | None = None
    notes: str | None = None
    created_at: str
    updated_at: str | None = None


class LearningAccountsIn(BaseModel):
    freecodecamp_username: str | None = None


class LearningAccountsOut(BaseModel):
    username: str
    freecodecamp_username: str | None = None
    last_cert_sync_at: str | None = None


class LearningAccountStatsOut(BaseModel):
    provider: str
    username: str | None = None
    configured: bool
    checked: int
    found_public: int
    public_completion_percent: int
    local_total: int
    local_pending: int
    local_verified: int
    local_rejected: int
    last_cert_sync_at: str | None = None
    items: list[dict] = Field(default_factory=list)


class AutoSyncResultOut(BaseModel):
    provider: str
    username: str | None = None
    checked: int
    found: int
    newly_verified: int
    items: list[dict] = Field(default_factory=list)


class QuestOut(BaseModel):
    key: str
    title: str
    description: str
    reward_xp: int
    completed: bool
    claimed: bool


class QuestListOut(BaseModel):
    username: str
    date: str
    quests: list[QuestOut] = Field(default_factory=list)


class QuestClaimIn(BaseModel):
    quest_key: str


class ChallengeOut(BaseModel):
    key: str
    title: str
    description: str
    reward_xp: int
    completed: bool
    claimed: bool


class ChallengeListOut(BaseModel):
    username: str
    week_start: str
    challenges: list[ChallengeOut] = Field(default_factory=list)


class ChallengeClaimIn(BaseModel):
    challenge_key: str


class RecommendationActionIn(BaseModel):
    dimension_key: str | None = None
    module_title: str
    module_url: str
    action: str | None = None
    action_type: str | None = None
    rating: int | None = Field(default=None, ge=1, le=5)
    feedback: str | None = None


class AdminEvaluationMetricsOut(BaseModel):
    total_students: int
    ai_model_provider: str
    ai_model_name: str
    ai_fallback_strategy: str
    recommendation_actions_total: int
    recommendation_acceptance_rate: int
    recommendation_ratings_total: int
    recommendation_relevance_rate: int
    tracked_portfolios_total: int
    portfolio_completeness_rate: int
    ai_eval_model: str | None = None
    ai_eval_dataset_rows: int | None = None
    ai_eval_train_rows: int | None = None
    ai_eval_validation_rows: int | None = None
    ai_eval_test_rows: int | None = None
    rouge1: float | None = None
    rouge2: float | None = None
    rougeL: float | None = None
    bleu: float | None = None
    bertscore_precision: float | None = None
    bertscore_recall: float | None = None
    bertscore_f1: float | None = None


class AdminEvaluationPredictionSampleOut(BaseModel):
    row_number: int
    input: str
    output: str | None = None
    prediction: str | None = None
    reference: str | None = None


class AdminEvaluationPredictionsOut(BaseModel):
    total_rows: int
    sample_count: int
    samples: list[AdminEvaluationPredictionSampleOut] = Field(default_factory=list)


class ValidationBulkItemIn(BaseModel):
    repo_name: str
    status: str
    comment: str | None = None


class ValidationBulkIn(BaseModel):
    student_id: int
    items: list[ValidationBulkItemIn]


class CertificateReviewBulkItemIn(BaseModel):
    certificate_id: int
    status: str
    reviewer_note: str | None = None


class CertificateReviewBulkIn(BaseModel):
    items: list[CertificateReviewBulkItemIn]


class ResearchAnalyticsOut(BaseModel):
    recommendation_acceptance_rate: int
    recommendation_ratings_total: int
    recommendation_relevance_rate: int
    weekly_login_frequency: float
    weekly_portfolio_update_frequency: float
    active_students_14d: int
