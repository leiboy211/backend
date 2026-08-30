from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models import Badge


def _badge_keep_key(badge: Badge) -> tuple[int, int, int]:
    return (
        1 if badge.claimed else 0,
        1 if badge.achieved else 0,
        int(badge.id or 0),
    )


def dedupe_badges_for_user(db: Session, user_id: int) -> None:
    badges = db.query(Badge).filter(Badge.user_id == user_id).all()
    if len(badges) <= 1:
        return

    grouped: dict[str, list[Badge]] = {}
    for badge in badges:
        grouped.setdefault(str(badge.label or ""), []).append(badge)

    for rows in grouped.values():
        if len(rows) <= 1:
            continue
        keep = max(rows, key=_badge_keep_key)
        for row in rows:
            if row.id != keep.id:
                db.delete(row)

    db.flush()


def upsert_badges(
    db: Session,
    user_id: int,
    generated_badges: list[dict],
    *,
    preserve_achieved: bool = True,
    clear_claimed_when_unachieved: bool = False,
) -> None:
    dedupe_badges_for_user(db, user_id)

    existing_badges = {
        badge.label: badge
        for badge in db.query(Badge).filter(Badge.user_id == user_id).all()
    }
    seen_labels: set[str] = set()

    for badge in generated_badges:
        label = str(badge["label"])
        # Do not insert the same achievement twice when model/rule output
        # contains duplicate labels during one recompute.
        if label in seen_labels:
            continue
        seen_labels.add(label)
        existing = existing_badges.get(label)
        if existing:
            existing.description = badge["description"]
            existing.criteria = badge["criteria"]
            existing.rarity = badge["rarity"]
            if preserve_achieved:
                existing.achieved = bool(existing.achieved) or bool(badge["achieved"])
            else:
                existing.achieved = bool(badge["achieved"])
            if clear_claimed_when_unachieved and not existing.achieved:
                existing.claimed = False
        else:
            new_badge = Badge(
                user_id=user_id,
                label=label,
                description=badge["description"],
                criteria=badge["criteria"],
                rarity=badge["rarity"],
                achieved=badge["achieved"],
                claimed=badge.get("claimed", False),
            )
            db.add(new_badge)
            existing_badges[label] = new_badge

    for label, stale in existing_badges.items():
        if label not in seen_labels:
            db.delete(stale)

    db.flush()


def repair_badge_duplicates(engine: Engine) -> None:
    """Collapse duplicate badge rows and add a DB-level unique index."""

    with engine.begin() as connection:
        try:
            duplicate_groups = connection.execute(
                text(
                    """
                    SELECT user_id, label
                    FROM badges
                    GROUP BY user_id, label
                    HAVING COUNT(*) > 1
                    """
                )
            ).fetchall()
        except Exception:
            return

        for user_id, label in duplicate_groups:
            rows = connection.execute(
                text(
                    """
                    SELECT id
                    FROM badges
                    WHERE user_id = :user_id AND label = :label
                    ORDER BY
                        CASE WHEN claimed THEN 1 ELSE 0 END DESC,
                        CASE WHEN achieved THEN 1 ELSE 0 END DESC,
                        id DESC
                    """
                ),
                {"user_id": user_id, "label": label},
            ).fetchall()
            if len(rows) <= 1:
                continue
            keep_id = rows[0][0]
            connection.execute(
                text("DELETE FROM badges WHERE user_id = :user_id AND label = :label AND id != :keep_id"),
                {"user_id": user_id, "label": label, "keep_id": keep_id},
            )

        try:
            connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_badges_user_label ON badges (user_id, label)"))
        except Exception:
            return
