from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path

import requests

from app.core.config import settings
from app.services.inference_utils import _normalize_inference
from app.services.learning_path import _normalize_steps

logger = logging.getLogger(__name__)


def _extract_json(content: str) -> dict | None:
    if not content:
        return None
    text = content.strip()
    if text.startswith("{") and text.endswith("}"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


@lru_cache(maxsize=2)
def _load_generator(model_name: str):
    try:
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer, pipeline
    except ImportError as exc:
        raise RuntimeError("Install transformers, torch, and sentencepiece to use FLAN-T5 inference.") from exc

    local_files_only = Path(model_name).exists()
    tokenizer = AutoTokenizer.from_pretrained(
        model_name,
        local_files_only=local_files_only,
        clean_up_tokenization_spaces=True,
    )
    model = AutoModelForSeq2SeqLM.from_pretrained(model_name, local_files_only=local_files_only)
    return pipeline(
        "text2text-generation",
        model=model,
        tokenizer=tokenizer,
    )


def warmup_model(model_name: str) -> None:
    if settings.hf_token:
        logger.info("Skipping local FLAN-T5 warmup; inference is configured through Hugging Face API.")
        return
    try:
        _load_generator(model_name)
        logger.info("FLAN-T5 warmup completed for %s", model_name)
    except Exception as exc:
        logger.warning("FLAN-T5 warmup failed for %s: %s", model_name, str(exc)[:240])


def _generate_json(model_name: str, prompt: str, max_new_tokens: int = 512) -> dict | None:
    content = _generate_text(model_name, prompt, max_new_tokens=max_new_tokens)
    return _extract_json(content)


def _generate_text(model_name: str, prompt: str, max_new_tokens: int = 512) -> str:
    if settings.hf_token:
        return _generate_text_remote(model_name, prompt, max_new_tokens=max_new_tokens)
    try:
        generator = _load_generator(model_name)
        result = generator(
            prompt,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            truncation=True,
        )
    except Exception as exc:
        logger.error("FLAN-T5 inference failed: %s", str(exc)[:240])
        raise RuntimeError("FLAN-T5 inference failed.") from exc

    if not result:
        return ""
    return str(result[0].get("generated_text") or "").strip()


def _generate_text_remote(model_name: str, prompt: str, max_new_tokens: int = 512) -> str:
    base_url = (settings.hf_endpoint_url or "").rstrip("/")
    if not base_url:
        raise RuntimeError("Hugging Face inference endpoint is not configured.")

    endpoint = base_url if base_url.endswith(model_name) else f"{base_url}/{model_name}"
    try:
        response = requests.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {settings.hf_token}",
                "Content-Type": "application/json",
            },
            json={
                "inputs": prompt,
                "parameters": {
                    "max_new_tokens": max_new_tokens,
                    "do_sample": False,
                    "return_full_text": False,
                },
                "options": {"wait_for_model": True},
            },
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        logger.error("Hugging Face API inference failed: %s", str(exc)[:240])
        raise RuntimeError("Hugging Face API inference failed.") from exc

    if isinstance(payload, list) and payload:
        generated = payload[0].get("generated_text")
    elif isinstance(payload, dict):
        generated = payload.get("generated_text")
    else:
        generated = None
    if not generated:
        raise RuntimeError("Hugging Face API returned no generated text.")
    return str(generated).strip()


def _repo_signal_text(repos: list[dict]) -> str:
    signals: list[str] = []
    for repo in repos:
        for key in ("language", "languages", "topics"):
            value = repo.get(key)
            if isinstance(value, list):
                signals.extend(str(item) for item in value if item)
            elif value:
                signals.append(str(value))
        code_signals = repo.get("code_signals") or {}
        if isinstance(code_signals, dict):
            for value in code_signals.values():
                if isinstance(value, list):
                    signals.extend(str(item) for item in value if item)
                elif value:
                    signals.append(str(value))
    return " ".join(signals).lower()


def _all_repo_names(repos: list[dict]) -> list[str]:
    names: list[str] = []
    for repo in repos:
        name = str(repo.get("name") or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def _compact_portfolio_signals(repos: list[dict]) -> dict:
    languages: list[str] = []
    topics: list[str] = []
    frameworks: list[str] = []
    keywords: list[str] = []
    for repo in repos:
        langs = repo.get("languages") or []
        if isinstance(langs, list):
            languages.extend([str(lang) for lang in langs if lang])
        if repo.get("language"):
            languages.append(str(repo.get("language")))
        topics.extend([str(topic) for topic in (repo.get("topics") or []) if topic])
        code_signals = repo.get("code_signals") or {}
        frameworks.extend([str(item) for item in (code_signals.get("frameworks") or []) if item])
        keywords.extend([str(item) for item in (code_signals.get("keywords") or []) if item])
    def unique(values: list[str]) -> list[str]:
        result: list[str] = []
        for value in values:
            value = str(value).strip()
            if value and value not in result:
                result.append(value)
        return result
    return {
        "languages": unique(languages)[:12],
        "topics": unique(topics)[:12],
        "frameworks": unique(frameworks)[:10],
        "keywords": unique(keywords)[:12],
    }


def _structured_practice_from_flan_text(content: str, repos: list[dict]) -> dict | None:
    signal_text = f"{content} {_repo_signal_text(repos)}".lower()
    groups = [
        (
            "Frontend and Web Development",
            "Frontend Developer",
            {
                "frontend": "JavaScript",
                "web": "HTML",
                "ui": "CSS",
                "react": "JavaScript",
                "javascript": "JavaScript",
                "typescript": "TypeScript",
                "html": "HTML",
                "css": "CSS",
                "tailwind": "CSS",
            },
        ),
        (
            "Backend and Software Engineering",
            "Backend Developer",
            {
                "backend": "Python",
                "api": "Python",
                "server": "Python",
                "python": "Python",
                "java": "Java",
                "node": "Node",
                "fastapi": "Python",
                "sql": "SQL",
                "postgresql": "PostgreSQL",
            },
        ),
        (
            "Data Management and AI",
            "Data or AI Developer",
            {
                "data": "SQL",
                "ai": "Python",
                "ml": "Python",
                "machine learning": "Python",
                "tensorflow": "Python",
                "python": "Python",
                "jupyter": "Jupyter Notebook",
                "sql": "SQL",
            },
        ),
        (
            "Systems, Networking, and DevOps",
            "DevOps or Systems Developer",
            {
                "systems": "C",
                "devops": "Docker",
                "docker": "Docker",
                "cloud": "Docker",
                "linux": "C",
                "network": "C",
                "security": "C",
                "deployment": "Docker",
            },
        ),
    ]
    practice_dimensions: list[dict] = []
    career_suggestions: list[dict] = []
    for label, career, terms in groups:
        evidence = sorted({canonical for term, canonical in terms.items() if term in signal_text})
        if not evidence:
            continue
        confidence = min(90, 60 + len(evidence) * 6)
        practice_dimensions.append(
            {
                "label": label,
                "confidence": confidence,
                "evidence": evidence[:3],
            }
        )
        career_suggestions.append(
            {
                "title": career,
                "confidence": confidence,
                "reasoning": f"FLAN-T5 identified signals aligned with {label.lower()}.",
            }
        )
    if not practice_dimensions:
        return None
    return {
        "practice_dimensions": practice_dimensions[:4],
        "career_suggestions": career_suggestions[:4],
    }


def _focus_labels(practice_dimensions: list[dict]) -> tuple[str | None, str | None]:
    if not practice_dimensions:
        return None, None
    ordered = sorted(practice_dimensions, key=lambda item: int(item.get("confidence") or 0))
    weakest = ordered[0]
    strongest = ordered[-1]
    primary_label = str(strongest.get("label") or "").strip() or None
    weak_label = str(weakest.get("label") or "").strip() or None
    return primary_label, weak_label


def infer_practice_and_careers(model: str, repos: list[dict]) -> dict:
    compact_repos = [
        {
            "name": repo.get("name"),
            "description": repo.get("description"),
            "language": repo.get("language"),
            "languages": repo.get("languages"),
            "topics": repo.get("topics"),
            "code_signals": repo.get("code_signals") or {},
            "commit_count": repo.get("commit_count"),
        }
        for repo in repos
    ]
    def build_from_text() -> dict | None:
        text_prompt = (
            "Classify the student's strongest computing career area from these repositories. "
            "Answer with short skill and career words only.\n"
            f"Repositories: {json.dumps(compact_repos)}"
        )
        content = _generate_text(model, text_prompt, max_new_tokens=96)
        return _structured_practice_from_flan_text(content, compact_repos)

    # CPU-friendly path: ask FLAN-T5 for a compact signal first. The local
    # deterministic mapper turns that signal into the API contract.
    parsed = build_from_text()
    if not parsed:
        prompt = (
            "Return only valid JSON. Analyze these GitHub repositories for a computing student.\n"
            "Use this exact schema: "
            '{"practice_dimensions":[{"label":"Frontend and Web Development","confidence":70,"evidence":["HTML"]}],'
            '"career_suggestions":[{"title":"Frontend Engineer","confidence":70,"reasoning":"Short reason"}]}.\n'
            "Use confidence values from 0 to 100. Keep evidence as short repo or technology signals.\n"
            f"Repositories: {json.dumps(compact_repos)}"
        )
        parsed = _generate_json(model, prompt, max_new_tokens=256)
    if not parsed:
        raise RuntimeError("FLAN-T5 returned no usable response.")
    try:
        normalized = _normalize_inference(parsed)
    except Exception as exc:
        logger.error("FLAN-T5 practice JSON normalization failed: %s", str(exc)[:240])
        raise RuntimeError("FLAN-T5 returned invalid practice JSON.") from exc
    has_blank_evidence = any(not item.get("evidence") for item in normalized.get("practice_dimensions") or [])
    if has_blank_evidence:
        rebuilt = build_from_text()
        if rebuilt:
            normalized = _normalize_inference(rebuilt)
    if not (normalized.get("practice_dimensions") or normalized.get("career_suggestions")):
        raise RuntimeError("FLAN-T5 returned empty practice/career results.")
    return normalized


def infer_learning_path(
    model: str,
    repos: list[dict],
    detected_skills: list[str] | None = None,
    project_keywords: list[str] | None = None,
    practice_dimensions: list[dict] | None = None,
) -> list[dict]:
    detected_skills = detected_skills or []
    project_keywords = project_keywords or []
    practice_dimensions = practice_dimensions or []
    compact_repos = [
        {
            "name": repo.get("name"),
            "description": repo.get("description"),
            "language": repo.get("language"),
            "languages": repo.get("languages"),
            "topics": repo.get("topics"),
            "code_signals": repo.get("code_signals") or {},
            "commit_count": repo.get("commit_count"),
        }
        for repo in repos
    ]
    all_repo_names = _all_repo_names(repos)
    portfolio_signals = _compact_portfolio_signals(repos)
    primary_label, weak_label = _focus_labels(practice_dimensions)
    focus_text = ""
    if primary_label:
        focus_text += f"Primary focus dimension: {primary_label} (strongest signal).\n"
    if weak_label and weak_label != primary_label:
        focus_text += f"Weakness to strengthen: {weak_label}.\n"

    prompt = (
        "Return only valid JSON. Create a personalized learning path for a BSCS/BSIT student.\n"
        "Schema: "
        '{"steps":[{"title":"Build a REST API","description":"Short actionable description",'
        '"difficulty":"Beginner","estimated_xp":120,"tags":["backend","api"],"type":"Project",'
        '"resources":{"courses":[{"name":"freeCodeCamp","url":"https://www.freecodecamp.org/learn/"}],'
        '"tools":[{"name":"GitHub","url":"https://github.com/"}],"documentation":[]},'
        '"ai_explanation":"Why this fits","progression_logic":"What to do next","evidence":["repo signal"]}]}.\n'
        "Generate 5 to 8 steps. Include at least 2 Project steps, 1 Certification step, and 1 Course step. "
        "Make every step specific to the provided repositories. Each step must mention at least one repo name "
        "or concrete repo signal in the title or description, and include evidence with a repo name. "
        "Do not return a generic learning path that could fit every student.\n"
        f"{focus_text}"
        f"Detected skills: {json.dumps(detected_skills[:12])}\n"
        f"Project keywords: {json.dumps(project_keywords[:20])}\n"
        f"Practice dimensions: {json.dumps(practice_dimensions)}\n"
        f"Repositories: {json.dumps(compact_repos)}\n"
        f"All repository names: {json.dumps(all_repo_names)}\n"
        f"Portfolio signals: {json.dumps(portfolio_signals)}"
    )
    parsed = _generate_json(model, prompt, max_new_tokens=1024)
    if not parsed:
        raise RuntimeError("FLAN-T5 returned an empty learning-path response.")
    steps = _normalize_steps(parsed, max_steps=8)
    if not steps:
        raise RuntimeError("FLAN-T5 returned invalid learning-path steps.")
    return steps


def infer_project_learning_paths(
    model: str,
    repos: list[dict],
    detected_skills: list[str] | None = None,
    project_keywords: list[str] | None = None,
    practice_dimensions: list[dict] | None = None,
) -> list[dict]:
    if not repos:
        return []
    detected_skills = detected_skills or []
    project_keywords = project_keywords or []
    practice_dimensions = practice_dimensions or []
    compact_repos = [
        {
            "name": repo.get("name"),
            "description": repo.get("description"),
            "language": repo.get("language"),
            "languages": repo.get("languages"),
            "topics": repo.get("topics"),
            "code_signals": repo.get("code_signals") or {},
        }
        for repo in repos[:8]
    ]
    prompt = (
        "Return only valid JSON. Generate per-project learning paths for these GitHub repositories.\n"
        "Schema: "
        '{"projects":[{"repo_name":"Repo name","steps":[{"title":"Task title","reason":"Why this helps",'
        '"tags":["testing"],"difficulty":"Beginner","reward_xp":100,"evidence":["repo signal"]}]}]}.\n'
        "Provide 3 to 5 steps per project. Make steps specific to the repo signals.\n"
        f"Detected skills: {json.dumps(detected_skills[:12])}\n"
        f"Project keywords: {json.dumps(project_keywords[:20])}\n"
        f"Practice dimensions: {json.dumps(practice_dimensions)}\n"
        f"Repositories: {json.dumps(compact_repos)}"
    )
    parsed = _generate_json(model, prompt, max_new_tokens=1024)
    if not parsed:
        raise RuntimeError("FLAN-T5 returned an empty project-path response.")

    projects = parsed.get("projects") or []
    if not projects:
        raise RuntimeError("FLAN-T5 returned no project paths.")

    normalized_projects: list[dict] = []
    for item in projects:
        repo_name = str(item.get("repo_name") or "").strip() or "Unnamed repo"
        steps = _normalize_steps({"steps": item.get("steps") or []}, max_steps=5, enforce_contract=False)
        if not steps:
            raise RuntimeError(f"FLAN-T5 returned invalid steps for project: {repo_name}.")
        normalized_projects.append({"repo_name": repo_name, "steps": steps})

    if not normalized_projects:
        raise RuntimeError("FLAN-T5 returned no valid project paths.")
    return normalized_projects


def generate_learning_step_actions(model: str, steps: list[dict], repos: list[dict]) -> list[str]:
    compact_steps = [
        {
            "title": step.get("title"),
            "description": step.get("description") or step.get("reason"),
            "difficulty": step.get("difficulty"),
            "type": step.get("type"),
            "tags": step.get("tags") or [],
            "evidence": step.get("evidence") or [],
        }
        for step in steps[:8]
    ]
    compact_repos = [
        {
            "name": repo.get("name"),
            "description": repo.get("description"),
            "language": repo.get("language"),
            "topics": repo.get("topics"),
        }
        for repo in repos[:6]
    ]
    prompt = (
        "Return only valid JSON. For each learning path step, write a unique, detailed, student-facing "
        "next action plan. Do not mention FLAN-T5, AI model, rule-based logic, or system internals. "
        "Each action must be 2 to 3 sentences, practical, and different from the other actions. "
        "Use the student's GitHub repository context when useful.\n"
        'Schema: {"actions":["Action for step 1","Action for step 2"]}\n'
        f"Repositories: {json.dumps(compact_repos)}\n"
        f"Learning path steps: {json.dumps(compact_steps)}"
    )
    parsed = _generate_json(model, prompt, max_new_tokens=768)
    if not parsed:
        raise RuntimeError("FLAN-T5 returned no usable step action response.")
    raw_actions = parsed.get("actions") or []
    actions = [str(action).strip() for action in raw_actions if str(action).strip()]
    if len(actions) < len(compact_steps):
        raise RuntimeError("FLAN-T5 returned incomplete step actions.")
    return actions[: len(compact_steps)]
