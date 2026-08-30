from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import LearningPath, LearningPathStage, StageProgressUpdate


def sync_project_learning_paths(
    db: Session,
    user_id: int,
    projects: list[dict],
    *,
    personalization_key: str = "",
) -> None:
    """Materialize the generated project paths into queryable tables.

    The legacy JSON baseline remains intact for backwards compatibility while
    these tables become the clean source for Table Editor/admin reporting.
    """
    for project in projects:
        repo_name = str(project.get("repo_name") or "Unnamed repo").strip()
        path_level = max(1, int(project.get("path_level") or 1))
        path = (
            db.query(LearningPath)
            .filter(
                LearningPath.user_id == user_id,
                LearningPath.repo_name == repo_name,
                LearningPath.path_level == path_level,
            )
            .one_or_none()
        )
        if path is None:
            path = LearningPath(user_id=user_id, repo_name=repo_name, path_level=path_level)
            db.add(path)
            db.flush()

        path.status = "completed" if project.get("repo_completed") else "active"
        path.progress_percent = max(0, min(100, int(project.get("progress_percent") or 0)))
        path.personalization_key = personalization_key
        path.source_profile = {
            "repo_name": repo_name,
            "path_level": path_level,
            "repo_completed": bool(project.get("repo_completed")),
        }

        stages = list(project.get("steps") or [])
        updates = project.get("stage_progress_updates") or {}
        existing_stages = {
            stage.stage_index: stage
            for stage in db.query(LearningPathStage)
            .filter(LearningPathStage.learning_path_id == path.id)
            .all()
        }
        for index, step in enumerate(stages):
            stage = existing_stages.get(index)
            if stage is None:
                stage = LearningPathStage(learning_path_id=path.id, stage_index=index)
                db.add(stage)
                db.flush()
            stage.title = str(step.get("title") or f"Stage {index + 1}")[:255]
            stage.description = str(step.get("description") or step.get("reason") or "")
            stage.stage_type = str(step.get("type") or "Skill")
            stage.tag = str(step.get("tag") or "")[:120] or None
            stage.difficulty = str(step.get("difficulty") or "Beginner")
            stage.reward_xp = int(step.get("reward_xp") or step.get("estimated_xp") or 0)
            stage.resources = step.get("resources") or {}
            stage.evidence = step.get("evidence") or []
            stage.status = str(step.get("status") or "todo")

            raw_update = updates.get(stage.title) if isinstance(updates, dict) else None
            if isinstance(raw_update, dict):
                latest = (
                    db.query(StageProgressUpdate)
                    .filter(StageProgressUpdate.learning_path_stage_id == stage.id)
                    .order_by(StageProgressUpdate.updated_at.desc(), StageProgressUpdate.id.desc())
                    .first()
                )
                if latest is None:
                    latest = StageProgressUpdate(
                        learning_path_stage_id=stage.id,
                        user_id=user_id,
                    )
                    db.add(latest)
                latest.comment = raw_update.get("comment")
                latest.proof_items = raw_update.get("proof_items") or []
                latest.review_status = str(raw_update.get("review_status") or "pending")
                latest.admin_feedback = raw_update.get("admin_feedback")

        for index, stale in existing_stages.items():
            if index >= len(stages):
                db.delete(stale)

