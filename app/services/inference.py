from __future__ import annotations

import logging
import hashlib
from pathlib import Path

from app.core.config import settings
from app.services import flan_t5
from app.services import llm_refiner
from app.services.inference_utils import _pad_career_suggestions
from app.services.learning_path import (
    _dimension_key_from_label,
    _dimension_keywords,
    _normalize_steps,
    _rule_based_learning_path,
    _rule_based_project_path,
    _stable_rotate,
)

logger = logging.getLogger(__name__)


def _llm_personalization_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12] if value else ""


def _local_flan_model_path() -> str | None:
    base_dir = Path(__file__).resolve().parents[2]
    local_dir = base_dir / "models" / "final_flan_t5_github_recommender"
    if local_dir.exists():
        return str(local_dir)
    return None


def _flan_model() -> str:
    if settings.flan_t5_model:
        return settings.flan_t5_model
    local_model = _local_flan_model_path()
    return local_model or "google/flan-t5-base"


def _repo_values(repo: dict, key: str) -> list[str]:
    value = repo.get(key)
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if isinstance(value, dict):
        return [str(item) for item in value.keys() if item]
    if value:
        return [str(value)]
    return []


def _fallback_practice_and_careers(repos: list[dict]) -> dict:
    groups = {
        "frontend": {
            "label": "Frontend and Web Development",
            "career": "Frontend Developer",
            "terms": {"javascript", "typescript", "html", "css", "react", "vue", "svelte", "tailwind"},
        },
        "backend": {
            "label": "Backend and Software Engineering",
            "career": "Backend Developer",
            "terms": {"python", "java", "c#", "go", "php", "ruby", "node", "node.js", "api", "fastapi"},
        },
        "data": {
            "label": "Data Management and AI",
            "career": "Data or AI Developer",
            "terms": {"sql", "postgresql", "mysql", "python", "jupyter notebook", "machine-learning", "ai", "data"},
        },
        "systems": {
            "label": "Systems, Networking, and DevOps",
            "career": "DevOps or Systems Developer",
            "terms": {"c", "c++", "rust", "docker", "linux", "devops", "network"},
        },
    }
    scores: dict[str, dict] = {
        key: {"score": 0, "evidence": []}
        for key in groups
    }

    for repo in repos:
        signals = []
        signals.extend(_repo_values(repo, "language"))
        signals.extend(_repo_values(repo, "languages"))
        signals.extend(_repo_values(repo, "topics"))
        signals.extend(_repo_values(repo, "code_signals"))
        lowered = {item.lower() for item in signals}
        for group, meta in groups.items():
            matched = sorted(lowered & meta["terms"])
            if not matched:
                continue
            scores[group]["score"] += len(matched)
            for item in matched:
                if item not in scores[group]["evidence"]:
                    scores[group]["evidence"].append(item)

    ordered = sorted(scores.items(), key=lambda item: item[1]["score"], reverse=True)
    practice_dimensions = []
    career_suggestions = []
    for group, result in ordered:
        if result["score"] <= 0:
            continue
        confidence = min(90, 55 + result["score"] * 10)
        evidence = [item.title() for item in result["evidence"][:3]]
        practice_dimensions.append(
            {
                "label": groups[group]["label"],
                "confidence": confidence,
                "evidence": evidence,
            }
        )
        career_suggestions.append(
            {
                "title": groups[group]["career"],
                "confidence": confidence,
                "reasoning": "Based on repository languages, topics, and code signals.",
            }
        )

    if not practice_dimensions:
        practice_dimensions = [
            {
                "label": "Software Development Fundamentals",
                "confidence": 50,
                "evidence": ["GitHub repositories"],
            }
        ]
        career_suggestions = [
            {
                "title": "Software Developer",
                "confidence": 50,
                "reasoning": "Based on available GitHub repository activity.",
            }
        ]

    return {
        "practice_dimensions": practice_dimensions[:4],
        "career_suggestions": _pad_career_suggestions(career_suggestions),
    }


def infer_practice_and_careers(repos: list[dict]) -> dict:
    try:
        return flan_t5.infer_practice_and_careers(_flan_model(), repos)
    except Exception as exc:
        logger.warning("Using deterministic inference fallback: %s", exc)
        return _fallback_practice_and_careers(repos)


def _model_signal_summary(practice_dimensions: list[dict] | None) -> str:
    dimensions = practice_dimensions or []
    if not dimensions:
        return ""
    top = sorted(dimensions, key=lambda item: int(item.get("confidence") or 0), reverse=True)[:2]
    labels = [str(item.get("label") or "").strip() for item in top if str(item.get("label") or "").strip()]
    if not labels:
        return ""
    return ", ".join(labels)


def _focus_dimension_keys(practice_dimensions: list[dict] | None) -> tuple[str | None, str | None]:
    if not practice_dimensions:
        return None, None
    ordered = sorted(practice_dimensions, key=lambda item: int(item.get("confidence") or 0))
    weakest = ordered[0]
    strongest = ordered[-1]
    weak_key = _dimension_key_from_label(str(weakest.get("label") or ""))
    strong_key = _dimension_key_from_label(str(strongest.get("label") or ""))
    return strong_key, weak_key


def _step_focus_text(step: dict) -> str:
    parts = [
        step.get("title"),
        step.get("description"),
        step.get("reason"),
        step.get("ai_explanation"),
        step.get("progression_logic"),
    ]
    tags = step.get("tags") or []
    if isinstance(tags, list):
        parts.extend(tags)
    parts.append(step.get("tag"))
    parts.append(step.get("dimension_key"))
    evidence = step.get("evidence") or []
    if isinstance(evidence, list):
        parts.extend(evidence)
    return " ".join(str(item or "") for item in parts).lower()


def _step_matches_focus(step: dict, dimension_key: str, keywords: set[str]) -> bool:
    if not dimension_key:
        return False
    if str(step.get("dimension_key") or "").strip().lower() == dimension_key:
        return True
    tag = str(step.get("tag") or "").strip().lower()
    if tag == dimension_key:
        return True
    tags = [str(value).strip().lower() for value in (step.get("tags") or []) if str(value).strip()]
    if dimension_key in tags:
        return True
    text = _step_focus_text(step)
    return any(keyword in text for keyword in keywords)


def _prioritize_steps_by_focus(steps: list[dict], practice_dimensions: list[dict] | None) -> list[dict]:
    if not steps:
        return steps
    primary_key, weak_key = _focus_dimension_keys(practice_dimensions)
    if not primary_key and not weak_key:
        return steps
    if primary_key and weak_key and primary_key == weak_key:
        return steps

    primary_keywords = _dimension_keywords(primary_key) if primary_key else set()
    weak_keywords = _dimension_keywords(weak_key) if weak_key else set()

    primary_steps: list[dict] = []
    weak_steps: list[dict] = []
    other_steps: list[dict] = []

    for step in steps:
        if primary_key and _step_matches_focus(step, primary_key, primary_keywords):
            primary_steps.append(step)
        elif weak_key and _step_matches_focus(step, weak_key, weak_keywords):
            weak_steps.append(step)
        else:
            other_steps.append(step)

    return primary_steps + weak_steps + other_steps


def _repo_names(repos: list[dict]) -> list[str]:
    names = [str(repo.get("name") or "").strip() for repo in repos]
    return [name for name in names if name]


def _repo_signals(repos: list[dict]) -> list[str]:
    signals: list[str] = []
    for repo in repos:
        for key in ("language", "languages", "topics"):
            value = repo.get(key)
            if isinstance(value, list):
                signals.extend([str(item) for item in value if item])
            elif value:
                signals.append(str(value))
        code_signals = repo.get("code_signals") or {}
        if isinstance(code_signals, dict):
            signals.extend([str(item) for item in (code_signals.get("frameworks") or []) if item])
            signals.extend([str(item) for item in (code_signals.get("keywords") or [])[:6] if item])
    curated: list[str] = []
    for signal in signals:
        if signal and signal not in curated:
            curated.append(signal)
    return curated[:6]


def _anchor_steps_to_repos(steps: list[dict], repos: list[dict]) -> list[dict]:
    if not steps:
        return steps
    repo_names = _repo_names(repos)
    if not repo_names:
        return steps
    signals = _repo_signals(repos)
    usage = {name: 0 for name in repo_names}

    def pick_repo() -> str:
        return min(repo_names, key=lambda name: (usage.get(name, 0), repo_names.index(name)))

    for step in steps:
        title = str(step.get("title") or "").strip()
        description = str(step.get("description") or step.get("reason") or "").strip()
        evidence = list(step.get("evidence") or [])
        text = f"{title} {description} {' '.join(str(item) for item in evidence)}".lower()

        matched_repo = next((name for name in repo_names if name.lower() in text), None)
        chosen_repo = matched_repo or pick_repo()
        if not matched_repo:
            usage[chosen_repo] = usage.get(chosen_repo, 0) + 1
            if chosen_repo not in evidence:
                evidence.insert(0, chosen_repo)

        if signals:
            for signal in signals:
                if signal.lower() in text or signal in evidence:
                    continue
                evidence.append(signal)
                if len(evidence) >= 3:
                    break

        step_type = str(step.get("type") or "").lower()
        if chosen_repo and chosen_repo.lower() not in title.lower():
            if "project" in step_type or "project" in title.lower():
                title = f"{title} ({chosen_repo})" if title else f"Project work ({chosen_repo})"

        if chosen_repo and chosen_repo.lower() not in description.lower():
            description = f"{description} Focus repo: {chosen_repo}.".strip()

        if title:
            step["title"] = title
        if description:
            step["description"] = description
            step["reason"] = description
        if evidence:
            step["evidence"] = evidence[:3]

    return steps


def _hybridize_steps_with_model_signals(
    steps: list[dict],
    practice_dimensions: list[dict] | None,
    detected_skills: list[str] | None,
) -> list[dict]:
    model_signal = _model_signal_summary(practice_dimensions)
    skills = [str(skill).strip() for skill in (detected_skills or []) if str(skill).strip()][:5]
    if not model_signal and not skills:
        return steps

    hybrid_steps: list[dict] = []
    for index, step in enumerate(steps):
        next_step = dict(step)
        evidence = list(next_step.get("evidence") or [])
        if model_signal and index < 3:
            evidence.append(f"Model signal: {model_signal}")
        if skills and index < 2:
            evidence.append(f"Detected skills: {', '.join(skills)}")
        next_step["evidence"] = list(dict.fromkeys(evidence))[:5]

        base_explanation = str(next_step.get("ai_explanation") or "").strip()
        step_reason = str(next_step.get("reason") or next_step.get("description") or "").strip()
        if step_reason:
            next_step["ai_explanation"] = step_reason
        elif base_explanation:
            next_step["ai_explanation"] = base_explanation

        hybrid_steps.append(next_step)
    return hybrid_steps


def _fallback_step_action(step: dict) -> str:
    title = str(step.get("title") or "this learning step").strip()
    text = " ".join(
        str(value or "")
        for value in [
            step.get("title"),
            step.get("description"),
            step.get("reason"),
            step.get("tag"),
            " ".join(step.get("tags") or []),
        ]
    ).lower()
    if any(term in text for term in ("database", "sql", "postgres", "mysql", "crud")):
        return (
            "Choose one existing project and design a small database schema for it. "
            "Implement one complete CRUD flow, then document the tables, fields, and sample data in the README."
        )
    if any(term in text for term in ("test", "testing", "quality", "pytest", "playwright")):
        return (
            "Pick one important feature and write a basic automated test for its expected behavior. "
            "Commit the test file and add a short note explaining what scenario the test protects."
        )
    if any(term in text for term in ("deploy", "deployment", "docker", "ci", "cd", "github actions")):
        return (
            "Prepare one project for deployment by adding environment setup notes and a repeatable run command. "
            "Then publish it or add a CI workflow, and place the live link or workflow badge in the README."
        )
    if any(term in text for term in ("frontend", "web", "ui", "react", "javascript", "typescript", "framework")):
        return (
            "Select one screen from an existing project and rebuild it as reusable components. "
            "Add responsive styling, then push a before-and-after update so the improvement is visible in GitHub."
        )
    if any(term in text for term in ("backend", "api", "server", "service", "auth")):
        return (
            "Create one small API endpoint connected to real project data. "
            "Test the endpoint with a request tool and add a short API usage example to the repository documentation."
        )
    return (
        f"Break \"{title}\" into two or three small implementation tasks. "
        "Finish the first task, commit it clearly, and update the README with what changed and what you will do next."
    )


def _enrich_steps_with_flan_actions(model: str, steps: list[dict], repos: list[dict]) -> list[dict]:
    if not steps:
        return steps
    if llm_refiner.is_enabled():
        # Fast hybrid mode: the API refiner writes the richer action text.
        # This avoids another local FLAN-T5 generation on CPU.
        return steps
    actions = [_fallback_step_action(step) for step in steps]

    enriched = []
    for index, step in enumerate(steps):
        next_step = dict(step)
        action = actions[index] if index < len(actions) else _fallback_step_action(step)
        next_step["progression_logic"] = action
        enriched.append(next_step)
    return enriched


def infer_learning_path(
    repos: list[dict],
    detected_skills: list[str] | None = None,
    project_keywords: list[str] | None = None,
    practice_dimensions: list[dict] | None = None,
    personalization_key: str = "",
) -> list[dict]:
    # FLAN-T5 stays responsible for upstream practice/career inference.
    # The visible learning path can now be generated by the optional LLM API,
    # while still keeping deterministic fallback logic for reliability.
    fallback_steps = _rule_based_learning_path(repos, personalization_key=personalization_key)
    fallback_steps = _hybridize_steps_with_model_signals(fallback_steps, practice_dimensions, detected_skills)
    fallback_steps = _enrich_steps_with_flan_actions(_flan_model(), fallback_steps, repos)
    fallback_steps = _anchor_steps_to_repos(fallback_steps, repos)
    fallback_steps = _prioritize_steps_by_focus(fallback_steps, practice_dimensions)

    try:
        steps = llm_refiner.generate_learning_path_steps(
            repos=repos,
            practice_dimensions=practice_dimensions,
            fallback_steps=fallback_steps,
            personalization_key=_llm_personalization_key(personalization_key),
        )
    except Exception as exc:
        logger.warning("LLM refiner failed for learning path, using fallback steps: %s", exc)
        steps = fallback_steps
    steps = _anchor_steps_to_repos(steps, repos)
    steps = _prioritize_steps_by_focus(steps, practice_dimensions)
    steps = _stable_rotate(steps, personalization_key, "main-learning-path-final")
    return steps


def infer_project_learning_paths(
    repos: list[dict],
    detected_skills: list[str] | None = None,
    project_keywords: list[str] | None = None,
    practice_dimensions: list[dict] | None = None,
    personalization_key: str = "",
) -> list[dict]:
    model_signal = _model_signal_summary(practice_dimensions)
    fallback_projects = [
        {
            "repo_name": str(repo.get("name") or "Unnamed repo"),
                "steps": _normalize_steps(
                    {"steps": _rule_based_project_path(repo, personalization_key=personalization_key, practice_dimensions=practice_dimensions)},
                max_steps=5,
                enforce_contract=False,
            ),
        }
        for repo in repos
    ]
    try:
        projects = llm_refiner.generate_project_learning_paths(
            repos=repos,
            practice_dimensions=practice_dimensions,
            fallback_projects=fallback_projects,
            max_projects=len(fallback_projects) or 1,
            personalization_key=_llm_personalization_key(personalization_key),
        )
    except Exception as exc:
        logger.warning("LLM refiner failed for project learning paths, using fallback projects: %s", exc)
        projects = fallback_projects
    # Keep the repo-specific anchor and remove repeated milestones returned by
    # the optional LLM refiner.
    fallback_by_repo = {str(item.get("repo_name") or "").strip(): item for item in fallback_projects}
    for project in projects:
        repo_name = str(project.get("repo_name") or "").strip()
        fallback_steps = (fallback_by_repo.get(repo_name) or {}).get("steps") or []
        project_steps = list(project.get("steps") or [])
        # The fallback is the canonical curriculum structure. Let the LLM
        # enrich the overall response, but never replace these repo/student-
        # specific stages with a generic checklist.
        if fallback_steps:
            project["steps"] = fallback_steps[:5]
            continue
        if fallback_steps and project_steps:
            anchor = fallback_steps[0]
            anchor_tag = str(anchor.get("tag") or "").strip().lower()
            has_anchor = any(
                anchor_tag and (
                    str(step.get("tag") or "").strip().lower() == anchor_tag
                    or anchor_tag in [str(tag).strip().lower() for tag in (step.get("tags") or [])]
                )
                for step in project_steps
            )
            if not has_anchor:
                project_steps = [anchor, *project_steps]
        deduped_steps = []
        seen_step_keys = set()
        for step in project_steps:
            step_key = " ".join(str(step.get("title") or step.get("description") or "").lower().split())
            if step_key and step_key not in seen_step_keys:
                seen_step_keys.add(step_key)
                deduped_steps.append(step)
        for fallback_step in fallback_steps:
            if len(deduped_steps) >= 5:
                break
            fallback_key = " ".join(str(fallback_step.get("title") or fallback_step.get("description") or "").lower().split())
            if fallback_key and fallback_key not in seen_step_keys:
                seen_step_keys.add(fallback_key)
                deduped_steps.append(fallback_step)
        if deduped_steps:
            project["steps"] = deduped_steps[:5]

    if not model_signal:
        return projects
    for project in projects:
        for step in project.get("steps") or []:
            step["ai_explanation"] = (
                f"Hybrid recommendation: FLAN-T5 practice signals ({model_signal}) were combined with "
                f"rule-based project analysis for this step."
            )
            evidence = list(step.get("evidence") or [])
            evidence.append(f"Model signal: {model_signal}")
            step["evidence"] = list(dict.fromkeys(evidence))[:5]
    return projects
