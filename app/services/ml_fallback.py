from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

_BUNDLE_PATH = Path(__file__).resolve().parents[2] / "models" / "it_cs_ml_fallback_bundle.joblib"


def is_available() -> bool:
    return _BUNDLE_PATH.exists()


@lru_cache(maxsize=1)
def _load_bundle():
    if not is_available():
        return None
    try:
        import joblib

        return joblib.load(_BUNDLE_PATH)
    except Exception as exc:
        logger.warning("ML fallback bundle could not be loaded: %s", str(exc)[:240])
        return None


def _repo_text(repos: list[dict]) -> str:
    parts: list[str] = []
    keys = ("name", "description", "readme", "language", "languages", "topics", "code_signals")
    for repo in repos or []:
        if not isinstance(repo, dict):
            continue
        for key in keys:
            value = repo.get(key)
            if isinstance(value, dict):
                parts.extend(str(item) for item in value.keys() if item)
                parts.extend(str(item) for item in value.values() if item)
            elif isinstance(value, (list, tuple, set)):
                parts.extend(str(item) for item in value if item)
            elif value:
                parts.append(str(value))
    return " ".join(parts).strip()


def _confidence(value: float, minimum: int = 35, maximum: int = 95) -> int:
    value = max(0.0, min(1.0, float(value)))
    return int(round(minimum + (maximum - minimum) * value))


def recommend(repos: list[dict]) -> dict | None:
    bundle = _load_bundle()
    profile_text = _repo_text(repos)
    if not bundle or not profile_text:
        return None

    try:
        classifier = bundle["career_classifier"]
        career_track = str(classifier.predict([profile_text])[0])
        track_info = (bundle.get("career_tracks") or {}).get(career_track) or {}
        keywords = [str(item) for item in (track_info.get("keywords") or []) if item]
        matched = [item for item in keywords if item.lower() in profile_text.lower()]
        fit_score = round(min(100.0, (len(matched) / max(len(keywords), 1)) * 100), 2)

        skill_model = bundle.get("skill_model")
        skill_binarizer = bundle.get("skill_binarizer")
        detected_skills: list[str] = []
        if skill_model is not None and skill_binarizer is not None:
            skill_vector = skill_model.predict([profile_text])
            detected_skills = [str(item) for item in skill_binarizer.inverse_transform(skill_vector)[0]]

        missing_skills = [item for item in keywords if item.lower() not in profile_text.lower()][:8]
        learning_path = [str(item) for item in (track_info.get("path") or []) if item]

        confidence = _confidence(fit_score / 100)
        return {
            "practice_dimensions": [
                {
                    "label": career_track,
                    "confidence": confidence,
                    "evidence": detected_skills[:5] or matched[:5] or ["Repository signals"],
                }
            ],
            "career_suggestions": [
                {
                    "title": career_track,
                    "confidence": confidence,
                    "reasoning": (
                        "Based on the technologies, project descriptions, topics, and code patterns "
                        f"found in your repositories, this track may be a good fit."
                    ),
                    "fit_score": fit_score,
                    "detected_skills": detected_skills[:12],
                    "missing_skills": missing_skills,
                }
            ],
            "learning_path": learning_path,
        }
    except Exception as exc:
        logger.warning("ML fallback inference failed: %s", str(exc)[:240])
        return None
