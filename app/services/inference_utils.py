from __future__ import annotations

LANGUAGE_GROUPS = {
    "frontend": {"JavaScript", "TypeScript", "HTML", "CSS", "Vue", "Svelte"},
    "backend": {
        "Python",
        "C#",
        "Java",
        "Go",
        "Ruby",
        "PHP",
        "Node",
        "Node.js",
        "SQL",
        "PostgreSQL",
        "SQLite",
    },
    "data": {"Jupyter Notebook", "Python", "R", "SQL", "PostgreSQL", "SQLite"},
    "systems": {"C", "C++", "Rust"},
}

CURRICULUM_LABELS = {
    "frontend": "Frontend and Web Development",
    "backend": "Backend and Software Engineering",
    "data": "Data Management and AI",
    "systems": "Systems, Networking, and DevOps",
}

DEFAULT_CAREER_SUGGESTIONS = [
    {
        "title": "Frontend Developer",
        "confidence": 50,
        "reasoning": "Initial recommendation based on the information currently available in your profile.",
    },
    {
        "title": "Backend Developer",
        "confidence": 50,
        "reasoning": "Initial recommendation based on the information currently available in your profile.",
    },
    {
        "title": "Data or AI Developer",
        "confidence": 50,
        "reasoning": "Initial recommendation based on the information currently available in your profile.",
    },
    {
        "title": "DevOps or Systems Developer",
        "confidence": 50,
        "reasoning": "Initial recommendation based on the information currently available in your profile.",
    },
]


def _pad_career_suggestions(careers: list[dict], target_count: int = 4) -> list[dict]:
    padded = list(careers)
    seen = {str(item.get("title") or "").strip().lower() for item in padded if item}
    for fallback in DEFAULT_CAREER_SUGGESTIONS:
        if len(padded) >= target_count:
            break
        title_key = str(fallback.get("title") or "").strip().lower()
        if not title_key or title_key in seen:
            continue
        padded.append(fallback.copy())
        seen.add(title_key)
    return padded[:target_count]


def _dedupe_evidence(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _normalize_inference(payload: dict) -> dict:
    practice = payload.get("practice_dimensions", []) or []
    careers = payload.get("career_suggestions", []) or []
    normalized_by_group: dict[str, dict] = {}
    for item in practice:
        evidence = item.get("evidence", []) or []
        label = (item.get("label") or "").lower()
        group = None
        if "frontend" in label or "web" in label or "ui" in label:
            group = "frontend"
        elif "backend" in label or "software engineering" in label or "api" in label:
            group = "backend"
        elif "data" in label or "ml" in label or "ai" in label:
            group = "data"
        elif "systems" in label or "tooling" in label or "devops" in label or "network" in label:
            group = "systems"
        if group:
            allowed = LANGUAGE_GROUPS[group]
            filtered = [lang for lang in evidence if lang in allowed]
            normalized_item = {
                "label": CURRICULUM_LABELS[group],
                "confidence": int(item.get("confidence") or 0),
                "evidence": _dedupe_evidence(filtered)[:3],
            }
            existing = normalized_by_group.get(group)
            if not existing or normalized_item["confidence"] > int(existing.get("confidence") or 0):
                normalized_by_group[group] = normalized_item
        else:
            item["evidence"] = _dedupe_evidence(evidence)[:3]

    ordered_practice = [
        normalized_by_group[group]
        for group in ("frontend", "backend", "data", "systems")
        if group in normalized_by_group
    ]
    if not ordered_practice:
        for item in practice:
            item["evidence"] = _dedupe_evidence(item.get("evidence", []) or [])[:3]
        ordered_practice = practice
    return {
        "practice_dimensions": ordered_practice,
        "career_suggestions": _pad_career_suggestions(careers),
    }
