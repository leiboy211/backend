from __future__ import annotations

import json
import logging
from typing import Any

import requests

from app.core.config import settings
from app.services.learning_path import _normalize_steps

logger = logging.getLogger(__name__)

CERTIFICATE_CATALOG: list[dict[str, Any]] = [
    {
        "id": "fcc-rwd",
        "title": "Responsive Web Design Certification",
        "provider": "freeCodeCamp",
        "url": "https://www.freecodecamp.org/learn/responsive-web-design/",
        "reward_xp": 720,
        "provider_aliases": ["freecodecamp", "free code camp"],
        "match_tokens": ["responsive web design", "html", "css"],
        "groups": ["frontend"],
    },
    {
        "id": "fcc-js",
        "title": "JavaScript Algorithms and Data Structures",
        "provider": "freeCodeCamp",
        "url": "https://www.freecodecamp.org/learn/javascript-algorithms-and-data-structures/",
        "reward_xp": 780,
        "provider_aliases": ["freecodecamp", "free code camp"],
        "match_tokens": ["javascript", "data structures", "algorithms"],
        "groups": ["frontend", "backend"],
    },
    {
        "id": "fcc-react",
        "title": "React Basics (via Frontend Certification)",
        "provider": "freeCodeCamp",
        "url": "https://www.freecodecamp.org/learn/front-end-development-libraries/",
        "reward_xp": 740,
        "provider_aliases": ["freecodecamp", "free code camp"],
        "match_tokens": ["react", "frontend", "ui", "component"],
        "groups": ["frontend"],
    },
    {
        "id": "odin-fullstack",
        "title": "Full Stack JavaScript Path",
        "provider": "The Odin Project",
        "url": "https://www.theodinproject.com/paths/full-stack-javascript",
        "reward_xp": 760,
        "provider_aliases": ["the odin project", "odin project"],
        "match_tokens": ["full stack", "javascript", "node"],
        "groups": ["frontend", "backend"],
    },
    {
        "id": "mslearn-web-dev",
        "title": "Web Development for Beginners",
        "provider": "Microsoft Learn",
        "url": "https://learn.microsoft.com/en-us/training/modules/build-simple-website/",
        "reward_xp": 680,
        "provider_aliases": ["microsoft learn", "microsoft"],
        "match_tokens": ["web development", "html", "css", "javascript"],
        "groups": ["frontend"],
    },
    {
        "id": "fcc-backend",
        "title": "Back End Development and APIs",
        "provider": "freeCodeCamp",
        "url": "https://www.freecodecamp.org/learn/back-end-development-and-apis/",
        "reward_xp": 800,
        "provider_aliases": ["freecodecamp", "free code camp"],
        "match_tokens": ["backend", "api", "server", "node"],
        "groups": ["backend"],
    },
    {
        "id": "fastapi-tutorial",
        "title": "FastAPI - Complete Tutorial",
        "provider": "FastAPI Official Docs",
        "url": "https://fastapi.tiangolo.com/tutorial/",
        "reward_xp": 750,
        "provider_aliases": ["fastapi", "fast api"],
        "match_tokens": ["fastapi", "api", "backend", "python api"],
        "groups": ["backend"],
    },
    {
        "id": "mslearn-backend",
        "title": "Build Web APIs with ASP.NET Core",
        "provider": "Microsoft Learn",
        "url": "https://learn.microsoft.com/en-us/training/paths/build-web-apis-with-aspnet-core/",
        "reward_xp": 710,
        "provider_aliases": ["microsoft learn", "microsoft"],
        "match_tokens": ["web api", "backend", "service"],
        "groups": ["backend"],
    },
    {
        "id": "fcc-database",
        "title": "Relational Database Certification (SQL & PostgreSQL)",
        "provider": "freeCodeCamp",
        "url": "https://www.freecodecamp.org/learn/relational-database/",
        "reward_xp": 790,
        "provider_aliases": ["freecodecamp", "free code camp"],
        "match_tokens": ["database", "sql", "postgresql", "crud"],
        "groups": ["database", "backend", "data"],
    },
    {
        "id": "mongodb-university",
        "title": "MongoDB Basics Course",
        "provider": "MongoDB University",
        "url": "https://learn.mongodb.com/courses/",
        "reward_xp": 700,
        "provider_aliases": ["mongodb university", "mongodb"],
        "match_tokens": ["mongodb", "nosql", "database"],
        "groups": ["database", "backend", "data"],
    },
    {
        "id": "fcc-data-analysis",
        "title": "Data Analysis with Python",
        "provider": "freeCodeCamp",
        "url": "https://www.freecodecamp.org/learn/data-analysis-with-python/",
        "reward_xp": 840,
        "provider_aliases": ["freecodecamp", "free code camp"],
        "match_tokens": ["data analysis", "python", "pandas", "analytics"],
        "groups": ["data", "ai"],
    },
    {
        "id": "fcc-ml",
        "title": "Machine Learning with Python",
        "provider": "freeCodeCamp",
        "url": "https://www.freecodecamp.org/learn/machine-learning-with-python/",
        "reward_xp": 920,
        "provider_aliases": ["freecodecamp", "free code camp"],
        "match_tokens": ["machine learning", "ml", "scikit-learn", "ai"],
        "groups": ["data", "ai"],
    },
    {
        "id": "kaggle-ml",
        "title": "Intro to Machine Learning",
        "provider": "Kaggle Learn",
        "url": "https://www.kaggle.com/learn/intro-to-machine-learning",
        "reward_xp": 760,
        "provider_aliases": ["kaggle learn", "kaggle"],
        "match_tokens": ["machine learning", "kaggle", "ml beginner"],
        "groups": ["data", "ai"],
    },
    {
        "id": "deeplearning-ai",
        "title": "Machine Learning for Beginners",
        "provider": "DeepLearning.AI",
        "url": "https://www.deeplearning.ai/short-courses/",
        "reward_xp": 730,
        "provider_aliases": ["deeplearning.ai", "deeplearning", "andrew ng"],
        "match_tokens": ["machine learning", "deep learning", "neural networks"],
        "groups": ["data", "ai"],
    },
    {
        "id": "fcc-qa",
        "title": "Quality Assurance Testing Certification",
        "provider": "freeCodeCamp",
        "url": "https://www.freecodecamp.org/learn/quality-assurance/",
        "reward_xp": 730,
        "provider_aliases": ["freecodecamp", "free code camp"],
        "match_tokens": ["quality assurance", "testing", "playwright", "pytest"],
        "groups": ["qa", "backend"],
    },
    {
        "id": "fcc-info-sec",
        "title": "Information Security Certification",
        "provider": "freeCodeCamp",
        "url": "https://www.freecodecamp.org/learn/information-security/",
        "reward_xp": 820,
        "provider_aliases": ["freecodecamp", "free code camp"],
        "match_tokens": ["security", "authentication", "oauth", "jwt"],
        "groups": ["security", "devops"],
    },
    {
        "id": "cisco-networking",
        "title": "Networking Basics (Cisco Skills for All)",
        "provider": "Cisco Networking Academy",
        "url": "https://www.netacad.com/courses/networking-basics",
        "reward_xp": 760,
        "provider_aliases": ["cisco networking academy", "netacad", "cisco"],
        "match_tokens": ["networking", "tcp", "ip", "socket"],
        "groups": ["networking", "devops"],
    },
    {
        "id": "docker-essentials",
        "title": "Docker Essentials - Getting Started",
        "provider": "Docker Official Training",
        "url": "https://docker-docs.umd.edu/guides/docker-fundamentals/",
        "reward_xp": 770,
        "provider_aliases": ["docker", "containerization"],
        "match_tokens": ["docker", "container", "deployment", "devops"],
        "groups": ["devops", "cloud"],
    },
    {
        "id": "aws-cloud",
        "title": "AWS Cloud Practitioner Essentials",
        "provider": "AWS Skill Builder",
        "url": "https://explore.skillbuilder.aws/learn/course/15091/aws-cloud-practitioner-essentials",
        "reward_xp": 780,
        "provider_aliases": ["aws skill builder", "aws"],
        "match_tokens": ["cloud", "aws", "ec2", "s3"],
        "groups": ["cloud", "devops"],
    },
    {
        "id": "mslearn-devops",
        "title": "DevOps Engineer Learning Path",
        "provider": "Microsoft Learn",
        "url": "https://learn.microsoft.com/en-us/training/career-paths/devops-engineer",
        "reward_xp": 800,
        "provider_aliases": ["microsoft learn", "microsoft"],
        "match_tokens": ["devops", "ci", "cd", "pipeline", "deployment"],
        "groups": ["cloud", "devops"],
    },
]


def _api_keys() -> list[str]:
    keys = [
        settings.llm_refiner_api_key,
        settings.llm_refiner_api_key_2,
    ]
    cleaned: list[str] = []
    for key in keys:
        value = (key or "").strip()
        if value and value not in cleaned:
            cleaned.append(value)
    return cleaned


def _enabled() -> bool:
    if settings.use_llm_refiner is False:
        return False
    return bool(_api_keys())


def _use_json_mode() -> bool:
    provider = (settings.llm_refiner_provider or "").strip().lower()
    return provider not in {"groq"}


def is_enabled() -> bool:
    return _enabled()


def _chat_completion(messages: list[dict[str, str]], max_tokens: int = 1400) -> str:
    if not _enabled():
        raise RuntimeError("LLM refiner is disabled or missing API key.")

    base_url = (settings.llm_refiner_base_url or "").rstrip("/")
    if not base_url:
        raise RuntimeError("LLM refiner base URL is empty.")

    payload = {
        "model": settings.llm_refiner_model,
        "messages": messages,
        "temperature": 0.35,
        "max_tokens": max_tokens,
    }
    if _use_json_mode():
        payload["response_format"] = {"type": "json_object"}

    last_error: Exception | None = None
    keys = _api_keys()
    for index, api_key in enumerate(keys, start=1):
        try:
            response = requests.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=45,
            )
            response.raise_for_status()
            payload = response.json()
            return str(payload["choices"][0]["message"]["content"])
        except requests.HTTPError as exc:
            last_error = exc
            status_code = exc.response.status_code if exc.response is not None else None
            if index < len(keys) and status_code in {401, 403, 408, 409, 429, 500, 502, 503, 504}:
                logger.info("LLM refiner key %s failed with HTTP %s; trying next key.", index, status_code)
                continue
            raise
        except requests.RequestException as exc:
            last_error = exc
            if index < len(keys):
                logger.info("LLM refiner key %s request failed; trying next key: %s", index, str(exc)[:160])
                continue
            raise

    raise RuntimeError("LLM refiner request failed for all configured API keys.") from last_error


def _extract_json(content: str) -> dict[str, Any]:
    content = (content or "").strip()
    if not content:
        raise RuntimeError("LLM refiner returned empty content.")
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        start = content.find("{")
        end = content.rfind("}")
        if start < 0 or end <= start:
            raise RuntimeError("LLM refiner returned non-JSON content.") from exc
        parsed = json.loads(content[start : end + 1])
    if not isinstance(parsed, dict):
        raise RuntimeError("LLM refiner returned invalid JSON payload.")
    return parsed


def _compact_repo(repo: dict) -> dict:
    return {
        "name": repo.get("name"),
        "description": repo.get("description"),
        "language": repo.get("language"),
        "languages": repo.get("languages"),
        "topics": repo.get("topics"),
        "commit_count": repo.get("commit_count"),
        "code_signals": repo.get("code_signals") or {},
    }


def _compact_step(step: dict) -> dict:
    return {
        "title": step.get("title"),
        "description": step.get("description") or step.get("reason"),
        "difficulty": step.get("difficulty"),
        "type": step.get("type"),
        "tags": step.get("tags") or [],
        "evidence": step.get("evidence") or [],
        "progression_logic": step.get("progression_logic"),
        "ai_explanation": step.get("ai_explanation"),
    }


def get_certificate_catalog() -> list[dict[str, Any]]:
    return [dict(item) for item in CERTIFICATE_CATALOG]


def _compact_dimension(item: dict) -> dict[str, Any]:
    return {
        "label": item.get("label"),
        "confidence": item.get("confidence"),
        "evidence": (item.get("evidence") or [])[:3],
    }


def refine_learning_steps(steps: list[dict], repos: list[dict]) -> list[dict]:
    """Polish FLAN-T5 learning steps without changing the system contract.

    FLAN-T5 remains the first recommendation source. This optional refiner only
    rewrites titles/descriptions/action text so the visible output is clearer
    and more specific to the student's actual repositories.
    """
    if not steps or not _enabled():
        return steps

    compact_steps = [_compact_step(step) for step in steps[:8]]
    compact_repos = [_compact_repo(repo) for repo in repos[:10]]
    prompt = (
        "You are refining output from a fine-tuned FLAN-T5 GitHub learning-path model. "
        "Do not replace the recommendation intent. Rewrite it so each step is specific, "
        "professional, and clearly tied to the student's repositories.\n\n"
        "Rules:\n"
        "- Return JSON only.\n"
        "- Keep the same number of steps and same order.\n"
        "- Make every step different from the others.\n"
        "- Mention at least one repository name in each step when repo names are available.\n"
        "- Do not invent projects, grades, private facts, or unavailable technologies.\n"
        "- Do not mention FLAN-T5, API, model, refiner, or rule-based logic.\n"
        "- Each progression_logic must be 2 to 4 practical sentences.\n\n"
        "- Keep evidence aligned with repo names or real tech signals.\n\n"
        'Schema: {"steps":[{"title":"...","description":"...","ai_explanation":"...",'
        '"progression_logic":"...","tags":["..."],"type":"Project","difficulty":"Beginner"}]}\n\n'
        f"Repositories: {json.dumps(compact_repos, ensure_ascii=False)}\n"
        f"Original FLAN-T5 steps: {json.dumps(compact_steps, ensure_ascii=False)}"
    )

    try:
        content = _chat_completion(
            [
                {
                    "role": "system",
                    "content": "You polish academic software-development learning paths into repository-specific guidance.",
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=1800,
        )
        parsed = _extract_json(content)
    except Exception as exc:
        logger.info("LLM refiner skipped after request/parse failure: %s", str(exc)[:240])
        return steps

    refined_items = parsed.get("steps") or []
    if not isinstance(refined_items, list) or len(refined_items) < len(steps):
        logger.info("LLM refiner skipped because it returned incomplete steps.")
        return steps

    refined_steps: list[dict] = []
    for index, original in enumerate(steps):
        item = refined_items[index] if index < len(refined_items) and isinstance(refined_items[index], dict) else {}
        next_step = dict(original)
        for key in ("title", "description", "ai_explanation", "progression_logic", "type", "difficulty"):
            value = str(item.get(key) or "").strip()
            if value:
                next_step[key] = value
                if key == "description":
                    next_step["reason"] = value
        tags = item.get("tags")
        if isinstance(tags, list):
            cleaned_tags = [str(tag).strip() for tag in tags if str(tag).strip()]
            if cleaned_tags:
                next_step["tags"] = cleaned_tags[:5]
        refined_steps.append(next_step)

    return refined_steps


def generate_learning_path_steps(
    *,
    repos: list[dict],
    practice_dimensions: list[dict] | None = None,
    fallback_steps: list[dict],
    max_steps: int = 8,
) -> list[dict]:
    if not fallback_steps or not _enabled():
        return fallback_steps

    compact_steps = [_compact_step(step) for step in fallback_steps[:max_steps]]
    compact_repos = [_compact_repo(repo) for repo in repos[:10]]
    compact_dimensions = [_compact_dimension(item) for item in (practice_dimensions or [])[:4] if isinstance(item, dict)]
    prompt = (
        "Generate a personalized software-development learning path for a student portfolio.\n"
        "Rules:\n"
        "- Return JSON only.\n"
        "- Use the schema {\"steps\":[...]}.\n"
        f"- Return between {min(5, max_steps)} and {max_steps} steps.\n"
        "- Keep the learning path practical, repository-specific, and outcome-based.\n"
        "- Every step must include: title, description, reason, type, difficulty, tags, evidence, ai_explanation, progression_logic.\n"
        "- Allowed type values: Project, Skill, Certification, Course.\n"
        "- Allowed difficulty values: Beginner, Intermediate, Advanced.\n"
        "- Mention at least one real repository name in each step when available.\n"
        "- Recommend certifications only when they logically fit the student's repo evidence and growth gaps.\n"
        "- Do not invent grades, internships, or unavailable technologies.\n"
        "- progression_logic must be 2 to 4 practical sentences.\n"
        "- evidence must be a short list of repo names, technologies, or clear portfolio signals.\n\n"
        f"Practice dimensions: {json.dumps(compact_dimensions, ensure_ascii=False)}\n"
        f"Repositories: {json.dumps(compact_repos, ensure_ascii=False)}\n"
        f"Fallback baseline steps: {json.dumps(compact_steps, ensure_ascii=False)}"
    )

    try:
        content = _chat_completion(
            [
                {
                    "role": "system",
                    "content": "You create repository-grounded academic learning paths for software students.",
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=2200,
        )
        parsed = _extract_json(content)
    except Exception as exc:
        logger.info("LLM learning-path generation skipped after request/parse failure: %s", str(exc)[:240])
        return fallback_steps

    steps = parsed.get("steps") or []
    if not isinstance(steps, list) or not steps:
        return fallback_steps

    try:
        normalized = _normalize_steps({"steps": steps}, max_steps=max_steps, enforce_contract=False)
    except Exception as exc:
        logger.info("LLM learning-path normalization failed: %s", str(exc)[:240])
        return fallback_steps
    return normalized or fallback_steps


def generate_project_learning_paths(
    *,
    repos: list[dict],
    practice_dimensions: list[dict] | None = None,
    fallback_projects: list[dict],
    max_projects: int | None = None,
    max_steps_per_project: int = 5,
    personalization_key: str = "",
) -> list[dict]:
    if not fallback_projects or not _enabled():
        return fallback_projects

    if max_projects is None:
        max_projects = len(fallback_projects)

    compact_repos = [_compact_repo(repo) for repo in repos[:max_projects]]
    compact_dimensions = [_compact_dimension(item) for item in (practice_dimensions or [])[:4] if isinstance(item, dict)]
    compact_projects = [
        {
            "repo_name": project.get("repo_name"),
            "steps": [_compact_step(step) for step in (project.get("steps") or [])[:max_steps_per_project]],
        }
        for project in fallback_projects[:max_projects]
    ]
    prompt = (
        "Generate per-repository learning paths for a student portfolio.\n"
        "Rules:\n"
        "- Return JSON only.\n"
        '- Use the schema {"projects":[{"repo_name":"...","steps":[...]}]}.\n'
        f"- Return at most {max_projects} projects and at most {max_steps_per_project} steps per project.\n"
        "- Keep each project's steps tightly scoped to that repository.\n"
        "- Every step must include: title, description, reason, type, difficulty, tags, evidence, ai_explanation, progression_logic.\n"
        "- Allowed type values: Project, Skill, Certification, Course.\n"
        "- Allowed difficulty values: Beginner, Intermediate, Advanced.\n"
        "- Do not invent repository names.\n\n"
        "- Vary the milestone emphasis and ordering when the student-specific key differs, while keeping every step grounded in the repository evidence.\n"
        f"Student-specific path key: {personalization_key}\n"
        f"Practice dimensions: {json.dumps(compact_dimensions, ensure_ascii=False)}\n"
        f"Repositories: {json.dumps(compact_repos, ensure_ascii=False)}\n"
        f"Fallback project paths: {json.dumps(compact_projects, ensure_ascii=False)}"
    )

    try:
        content = _chat_completion(
            [
                {
                    "role": "system",
                    "content": "You create repository-specific learning milestones for software students.",
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=2600,
        )
        parsed = _extract_json(content)
    except Exception as exc:
        logger.info("LLM project learning-path generation skipped after request/parse failure: %s", str(exc)[:240])
        return fallback_projects

    projects = parsed.get("projects") or []
    if not isinstance(projects, list) or not projects:
        return fallback_projects

    by_repo = {str(item.get("repo_name") or "").strip().lower(): item for item in fallback_projects}
    normalized_projects: list[dict] = []
    for item in projects[:max_projects]:
        if not isinstance(item, dict):
            continue
        repo_name = str(item.get("repo_name") or "").strip()
        if not repo_name:
            continue
        raw_steps = item.get("steps") or []
        if not isinstance(raw_steps, list) or not raw_steps:
            fallback = by_repo.get(repo_name.lower())
            if fallback:
                normalized_projects.append(dict(fallback))
            continue
        try:
            steps = _normalize_steps({"steps": raw_steps}, max_steps=max_steps_per_project, enforce_contract=False)
        except Exception:
            steps = []
        if not steps:
            fallback = by_repo.get(repo_name.lower())
            if fallback:
                normalized_projects.append(dict(fallback))
            continue
        normalized_projects.append({"repo_name": repo_name, "steps": steps})

    return normalized_projects or fallback_projects


def generate_certificate_suggestions(
    *,
    learning_path_steps: list[dict],
    project_learning_paths: list[dict] | None = None,
    career_suggestions: list[dict] | None = None,
    max_items: int = 6,
) -> list[dict[str, Any]]:
    if not learning_path_steps or not _enabled():
        return []

    catalog = [
        {
            "id": item["id"],
            "title": item["title"],
            "provider": item["provider"],
            "url": item["url"],
            "reward_xp": item["reward_xp"],
            "groups": item["groups"],
            "match_tokens": item["match_tokens"],
        }
        for item in CERTIFICATE_CATALOG
    ]
    compact_steps = [_compact_step(step) for step in learning_path_steps[:8]]
    compact_projects = [
        {
            "repo_name": project.get("repo_name"),
            "steps": [_compact_step(step) for step in (project.get("steps") or [])[:3]],
        }
        for project in (project_learning_paths or [])[:6]
        if isinstance(project, dict)
    ]
    compact_careers = [
        {
            "title": item.get("title"),
            "confidence": item.get("confidence"),
            "reasoning": item.get("reasoning"),
        }
        for item in (career_suggestions or [])[:3]
        if isinstance(item, dict)
    ]
    prompt = (
        "Select the best certificate or course-track recommendations for this student.\n"
        "Rules:\n"
        "- Return JSON only.\n"
        '- Use the schema {"items":[{"id":"catalog-id","reasoning":"..."}]}.\n'
        f"- Return at most {max_items} items.\n"
        "- Only use IDs from the provided catalog.\n"
        "- Prefer items that directly strengthen the student's current learning path and repo gaps.\n"
        "- Keep reasoning to 1 or 2 concise sentences and ground it in repo or learning-path evidence.\n"
        "- Do not recommend duplicate or near-duplicate tracks unless they serve clearly different goals.\n\n"
        f"Learning path steps: {json.dumps(compact_steps, ensure_ascii=False)}\n"
        f"Project learning paths: {json.dumps(compact_projects, ensure_ascii=False)}\n"
        f"Career suggestions: {json.dumps(compact_careers, ensure_ascii=False)}\n"
        f"Available catalog: {json.dumps(catalog, ensure_ascii=False)}"
    )

    try:
        content = _chat_completion(
            [
                {
                    "role": "system",
                    "content": "You recommend credible learning credentials that fit repository-based student growth plans.",
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=1600,
        )
        parsed = _extract_json(content)
    except Exception as exc:
        logger.info("LLM certificate suggestions skipped after request/parse failure: %s", str(exc)[:240])
        return []

    items = parsed.get("items") or []
    if not isinstance(items, list):
        return []

    catalog_map = {item["id"]: item for item in CERTIFICATE_CATALOG}
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items[:max_items]:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "").strip()
        if not item_id or item_id in seen or item_id not in catalog_map:
            continue
        base = dict(catalog_map[item_id])
        reasoning = str(item.get("reasoning") or "").strip()
        base["reasoning"] = reasoning or "Aligned with the current learning path."
        results.append(base)
        seen.add(item_id)
    return results


def generate_portfolio_summary(
    *,
    profile: dict[str, Any],
    repos: list[dict],
    practice_dimensions: list[dict] | None = None,
    career_suggestions: list[dict] | None = None,
    tech_stack: list[str] | None = None,
) -> str | None:
    """Generate a concise portfolio about-me summary when the optional LLM is available."""
    if not _enabled():
        return None

    compact_profile = {
        "display_name": profile.get("display_name") or profile.get("username"),
        "program": profile.get("program"),
        "year_level": profile.get("year_level"),
        "career_interest": profile.get("career_interest"),
        "target_role": profile.get("target_role"),
        "preferred_learning_style": profile.get("preferred_learning_style"),
    }
    compact_dimensions = [
        {
            "label": item.get("label"),
            "confidence": item.get("confidence"),
            "evidence": (item.get("evidence") or [])[:2],
        }
        for item in (practice_dimensions or [])[:3]
        if isinstance(item, dict)
    ]
    compact_careers = [
        {
            "title": item.get("title"),
            "confidence": item.get("confidence"),
        }
        for item in (career_suggestions or [])[:2]
        if isinstance(item, dict)
    ]
    compact_repos = [_compact_repo(repo) for repo in repos[:6]]
    compact_stack = [str(item).strip() for item in (tech_stack or []) if str(item).strip()][:8]

    prompt = (
        "Write a polished first-person About Me summary for a student software portfolio.\n"
        "Rules:\n"
        "- Return JSON only.\n"
        '- Use the schema {"summary":"..."}.\n'
        "- Write 2 to 4 sentences, around 60 to 110 words.\n"
        "- Sound confident, clear, and student-appropriate.\n"
        "- Mention only skills, project types, and goals supported by the provided data.\n"
        "- Do not invent internships, awards, clients, years of experience, or private facts.\n"
        "- Avoid filler buzzwords and avoid repeating the same technology names too many times.\n"
        "- If a target role exists, naturally connect the portfolio direction to that role.\n\n"
        f"Profile: {json.dumps(compact_profile, ensure_ascii=False)}\n"
        f"Tech stack: {json.dumps(compact_stack, ensure_ascii=False)}\n"
        f"Practice dimensions: {json.dumps(compact_dimensions, ensure_ascii=False)}\n"
        f"Career suggestions: {json.dumps(compact_careers, ensure_ascii=False)}\n"
        f"Repositories: {json.dumps(compact_repos, ensure_ascii=False)}"
    )

    try:
        content = _chat_completion(
            [
                {
                    "role": "system",
                    "content": "You write concise, credible portfolio summaries for student developers.",
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=220,
        )
        parsed = _extract_json(content)
    except Exception as exc:
        logger.info("Portfolio summary generation skipped after request/parse failure: %s", str(exc)[:240])
        return None

    summary = str(parsed.get("summary") or "").strip()
    return summary or None
