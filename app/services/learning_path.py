from __future__ import annotations

from collections import Counter
import hashlib
import json
import logging
import re

logger = logging.getLogger(__name__)

FRAMEWORK_KEYWORDS = {
    "react",
    "next",
    "vue",
    "nuxt",
    "svelte",
    "angular",
    "remix",
}

BACKEND_KEYWORDS = {
    "api",
    "backend",
    "server",
    "fastapi",
    "flask",
    "django",
    "express",
    "nestjs",
    "spring",
}

DATABASE_KEYWORDS = {
    "postgres",
    "postgresql",
    "mysql",
    "mongodb",
    "redis",
    "database",
    "orm",
}

TEST_KEYWORDS = {
    "test",
    "testing",
    "pytest",
    "jest",
    "vitest",
    "mocha",
    "cypress",
    "playwright",
}

DEPLOY_KEYWORDS = {
    "ci",
    "cd",
    "deploy",
    "docker",
    "kubernetes",
    "vercel",
    "render",
    "railway",
    "netlify",
}

FRONTEND_LANGS = {"javascript", "typescript", "html", "css"}
BACKEND_LANGS = {"python", "java", "c#", "go", "ruby", "php", "node", "node.js"}

DIMENSION_DEFINITIONS = {
    "frontend_engineering": {
        "label": "Frontend Engineering",
        "subtitle": "Web and Application Development",
    },
    "backend_systems_engineering": {
        "label": "Backend Systems Engineering",
        "subtitle": "Software Engineering and Backend Development",
    },
    "data_science_intelligence": {
        "label": "Data Science & Intelligence",
        "subtitle": "Data Management and Intelligent Systems",
    },
    "systems_devops_engineering": {
        "label": "Systems & DevOps Engineering",
        "subtitle": "Systems Administration, Networking, and DevOps",
    },
}

LEVEL_ORDER = ["Beginner", "Intermediate", "Advanced"]
VALID_DIFFICULTIES = set(LEVEL_ORDER)
VALID_STEP_TYPES = {"Project", "Skill", "Certification", "Course"}


def _stable_rotate(items: list[dict], personalization_key: str, namespace: str) -> list[dict]:
    """Apply stable account-specific ordering without making recommendations random."""
    if len(items) < 2 or not personalization_key:
        return items
    digest = hashlib.sha256(f"{namespace}:{personalization_key}".encode("utf-8")).digest()
    offset = int.from_bytes(digest[:4], "big") % len(items)
    return items[offset:] + items[:offset]

COMPETENCY_ACTIVITY_MAP = {
    "frontend_engineering": {
        "Beginner": [
            "Build responsive pages with semantic HTML, modern CSS, and JavaScript fundamentals.",
            "Implement reusable UI components and client-side routing in a small app.",
        ],
        "Intermediate": [
            "Integrate APIs, state management, and form validation in a multi-page application.",
            "Apply accessibility and component testing for critical user flows.",
        ],
        "Advanced": [
            "Optimize rendering performance, bundle strategy, and production monitoring.",
            "Ship a production-ready frontend module with robust test coverage and error handling.",
        ],
    },
    "backend_systems_engineering": {
        "Beginner": [
            "Build REST endpoints with structured routing and controller patterns.",
            "Implement CRUD operations and schema validation for core entities.",
        ],
        "Intermediate": [
            "Add authentication, authorization, and secure secret/config management.",
            "Write integration tests and standardized API error handling.",
        ],
        "Advanced": [
            "Design scalable service architecture with caching, queues, or async workers.",
            "Tune backend performance and observability for production workloads.",
        ],
    },
    "data_science_intelligence": {
        "Beginner": [
            "Prepare and clean datasets, then produce exploratory analysis reports.",
            "Model relational data and write SQL queries for reporting use cases.",
        ],
        "Intermediate": [
            "Build feature pipelines and evaluate ML models with clear metrics.",
            "Create dashboards or notebooks that communicate insights to stakeholders.",
        ],
        "Advanced": [
            "Deploy model inference services with monitoring for drift and data quality.",
            "Implement experiment tracking and versioning for reproducible ML workflows.",
        ],
    },
    "systems_devops_engineering": {
        "Beginner": [
            "Use Linux shell and scripting to automate repetitive project tasks.",
            "Containerize one project and document local environment setup.",
        ],
        "Intermediate": [
            "Set up CI/CD pipelines with lint, test, and deployment gates.",
            "Configure logging, alerting, and basic infrastructure security controls.",
        ],
        "Advanced": [
            "Design reliable deployment strategies (blue/green or rolling) with rollback plans.",
            "Improve reliability with infrastructure monitoring, scaling, and incident playbooks.",
        ],
    },
}


def _repo_tokens(repo: dict) -> set[str]:
    tokens: set[str] = set()
    for key in ("name", "description"):
        value = repo.get(key) or ""
        tokens.update(value.lower().replace("-", " ").split())
    for topic in repo.get("topics") or []:
        tokens.add(str(topic).lower())
    for lang in repo.get("languages") or []:
        tokens.add(str(lang).lower())
    if repo.get("language"):
        tokens.add(str(repo.get("language")).lower())
    code_signals = repo.get("code_signals") or {}
    for keyword in code_signals.get("keywords") or []:
        tokens.add(str(keyword).lower())
    for framework in code_signals.get("frameworks") or []:
        tokens.add(str(framework).lower())
    for test_fw in code_signals.get("testing_frameworks") or []:
        tokens.add(str(test_fw).lower())
    for architecture in code_signals.get("architecture") or []:
        tokens.add(str(architecture).lower())
    testing = code_signals.get("testing") or {}
    if testing.get("has_tests"):
        tokens.add("testing")
        tokens.add("test")
    devops = code_signals.get("devops") or {}
    if devops.get("has_ci"):
        tokens.add("ci")
    if devops.get("has_docker"):
        tokens.add("docker")
    if devops.get("has_kubernetes"):
        tokens.add("kubernetes")
    return tokens


def score_to_competency_level(score: int) -> str:
    if score <= 39:
        return "Beginner"
    if score <= 69:
        return "Intermediate"
    return "Advanced"


def _dimension_key_from_label(label: str) -> str:
    normalized = (label or "").strip().lower()
    if "frontend" in normalized:
        return "frontend_engineering"
    if "backend" in normalized:
        return "backend_systems_engineering"
    if "data" in normalized or "intelligence" in normalized or "ai" in normalized or "ml" in normalized:
        return "data_science_intelligence"
    return "systems_devops_engineering"


def build_competency_levels(practice_dimensions: list[dict]) -> list[dict]:
    by_key: dict[str, dict] = {}
    for item in practice_dimensions or []:
        key = _dimension_key_from_label(str(item.get("label") or ""))
        score = int(item.get("confidence") or 0)
        definition = DIMENSION_DEFINITIONS[key]
        by_key[key] = {
            "dimension_key": key,
            "dimension": definition["label"],
            "description": definition["subtitle"],
            "score_percent": max(0, min(100, score)),
            "level": score_to_competency_level(score),
            "evidence": (item.get("evidence") or [])[:3],
        }

    for key, definition in DIMENSION_DEFINITIONS.items():
        if key not in by_key:
            by_key[key] = {
                "dimension_key": key,
                "dimension": definition["label"],
                "description": definition["subtitle"],
                "score_percent": 0,
                "level": "Beginner",
                "evidence": [],
            }

    return sorted(by_key.values(), key=lambda item: item["score_percent"])


def identify_skill_gaps(competency_levels: list[dict]) -> list[dict]:
    ordered = sorted(competency_levels, key=lambda item: item.get("score_percent", 0))
    total = len(ordered)
    gaps: list[dict] = []
    for index, item in enumerate(ordered):
        if item["level"] == "Advanced":
            gap = "Maintain and optimize"
        elif item["level"] == "Intermediate":
            gap = "Progress to advanced implementation"
        else:
            gap = "Build foundational competency"

        if index <= 1:
            priority = "High"
        elif index == 2:
            priority = "Medium"
        else:
            priority = "Low"

        if total <= 2:
            priority = "High" if index == 0 else "Medium"

        gaps.append(
            {
                "dimension_key": item["dimension_key"],
                "dimension": item["dimension"],
                "score_percent": item["score_percent"],
                "current_level": item["level"],
                "target_level": "Advanced",
                "priority": priority,
                "gap_summary": gap,
            }
        )
    return gaps


def _order_gaps_for_path(gaps: list[dict], competency_levels: list[dict]) -> list[dict]:
    if not gaps or not competency_levels:
        return gaps
    ordered_levels = sorted(competency_levels, key=lambda item: int(item.get("score_percent") or 0))
    weakest_key = ordered_levels[0].get("dimension_key")
    strongest_key = ordered_levels[-1].get("dimension_key")
    used: set[str] = set()
    ordered: list[dict] = []

    for key in (strongest_key, weakest_key):
        if not key or key in used:
            continue
        match = next((gap for gap in gaps if gap.get("dimension_key") == key), None)
        if match:
            ordered.append(match)
            used.add(key)

    for gap in gaps:
        key = gap.get("dimension_key")
        if key in used:
            continue
        ordered.append(gap)
        if key:
            used.add(key)

    return ordered


def _priority_xp(priority: str, level: str) -> int:
    base = {"High": 140, "Medium": 110, "Low": 90}.get(priority, 90)
    level_bonus = {"Beginner": 0, "Intermediate": 20, "Advanced": 35}.get(level, 0)
    return base + level_bonus


def _normalize_difficulty(value: str | None) -> str:
    normalized = str(value or "").strip().capitalize()
    if normalized in VALID_DIFFICULTIES:
        return normalized
    return "Beginner"


def _normalize_step_type(value: str | None, title: str, tags: list[str]) -> str:
    normalized = str(value or "").strip().capitalize()
    if normalized in VALID_STEP_TYPES:
        return normalized

    title_l = title.lower()
    tags_l = [tag.lower() for tag in tags]
    token_text = " ".join([title_l] + tags_l)
    if any(token in token_text for token in ["certification", "cert", "exam", "az-900", "aws", "oracle"]):
        return "Certification"
    if any(token in token_text for token in ["course", "tutorial", "learn", "docs", "documentation"]):
        return "Course"
    if any(token in token_text for token in ["build", "create", "ship", "capstone", "project", "deploy"]):
        return "Project"
    return "Skill"


def _xp_for_difficulty(level: str, index: int) -> int:
    base = {"Beginner": 110, "Intermediate": 140, "Advanced": 180}.get(level, 120)
    # slight progression bump while staying in the requested 100-200 range
    return max(100, min(200, base + min(12, index * 4)))


def _resource_pack_from_tags(tags: list[str], step_type: str, title: str = "", description: str = "") -> dict:
    context = " ".join([title, description, *tags]).lower()
    category_packs = {
        "frontend": {
            "tokens": ["frontend", "javascript", "typescript", "react", "css", "html", "ui", "web"],
            "courses": [
                {"name": "MDN Learn Web Development", "url": "https://developer.mozilla.org/en-US/docs/Learn"},
                {"name": "freeCodeCamp Responsive Web Design", "url": "https://www.freecodecamp.org/learn/2022/responsive-web-design/"},
                {"name": "freeCodeCamp JavaScript Algorithms", "url": "https://www.freecodecamp.org/learn/javascript-algorithms-and-data-structures-v8/"},
                {"name": "Scrimba Learn JavaScript", "url": "https://scrimba.com/learn/learnjavascript"},
            ],
            "tools": [
                {"name": "CodePen", "url": "https://codepen.io/"},
                {"name": "Can I Use", "url": "https://caniuse.com/"},
                {"name": "Chrome DevTools", "url": "https://developer.chrome.com/docs/devtools/"},
            ],
            "documentation": [
                {"name": "JavaScript.info", "url": "https://javascript.info/"},
                {"name": "React Docs", "url": "https://react.dev/learn"},
                {"name": "TypeScript Handbook", "url": "https://www.typescriptlang.org/docs/"},
                {"name": "CSS Tricks Guides", "url": "https://css-tricks.com/guides/"},
            ],
        },
        "backend": {
            "tokens": ["backend", "api", "server", "fastapi", "express", "node", "http", "endpoint"],
            "courses": [
                {"name": "The Odin Project", "url": "https://www.theodinproject.com/"},
                {"name": "freeCodeCamp Back End Development and APIs", "url": "https://www.freecodecamp.org/learn/back-end-development-and-apis/"},
                {"name": "FastAPI Tutorial", "url": "https://fastapi.tiangolo.com/tutorial/"},
                {"name": "Node.js Learn", "url": "https://nodejs.org/en/learn"},
            ],
            "tools": [
                {"name": "Postman", "url": "https://www.postman.com/"},
                {"name": "Insomnia", "url": "https://insomnia.rest/"},
                {"name": "Swagger Editor", "url": "https://editor.swagger.io/"},
            ],
            "documentation": [
                {"name": "REST API Design Best Practices", "url": "https://learn.microsoft.com/en-us/azure/architecture/best-practices/api-design"},
                {"name": "FastAPI Docs", "url": "https://fastapi.tiangolo.com/"},
                {"name": "MDN HTTP Overview", "url": "https://developer.mozilla.org/en-US/docs/Web/HTTP/Overview"},
                {"name": "OpenAPI Specification", "url": "https://spec.openapis.org/oas/latest.html"},
            ],
        },
        "data": {
            "tokens": ["database", "sql", "data", "analytics", "python", "pandas", "numpy", "ml", "ai", "machine learning"],
            "courses": [
                {"name": "SQLBolt", "url": "https://sqlbolt.com/"},
                {"name": "freeCodeCamp Relational Database", "url": "https://www.freecodecamp.org/learn/relational-database/"},
                {"name": "Kaggle Microcourses", "url": "https://www.kaggle.com/learn"},
                {"name": "freeCodeCamp Data Analysis with Python", "url": "https://www.freecodecamp.org/learn/data-analysis-with-python/"},
            ],
            "tools": [
                {"name": "DB Fiddle", "url": "https://www.db-fiddle.com/"},
                {"name": "pgAdmin", "url": "https://www.pgadmin.org/"},
                {"name": "Jupyter Notebook", "url": "https://jupyter.org/"},
            ],
            "documentation": [
                {"name": "PostgreSQL Documentation", "url": "https://www.postgresql.org/docs/"},
                {"name": "Pandas User Guide", "url": "https://pandas.pydata.org/docs/user_guide/index.html"},
                {"name": "scikit-learn User Guide", "url": "https://scikit-learn.org/stable/user_guide.html"},
                {"name": "NumPy User Guide", "url": "https://numpy.org/doc/stable/user/"},
            ],
        },
        "testing": {
            "tokens": ["testing", "quality", "qa", "jest", "pytest", "playwright", "test"],
            "courses": [
                {"name": "Testing JavaScript", "url": "https://testingjavascript.com/"},
                {"name": "freeCodeCamp Quality Assurance", "url": "https://www.freecodecamp.org/learn/quality-assurance/"},
                {"name": "Test Automation University", "url": "https://testautomationu.applitools.com/"},
            ],
            "tools": [
                {"name": "GitHub Actions", "url": "https://docs.github.com/en/actions"},
                {"name": "Playwright", "url": "https://playwright.dev/"},
                {"name": "Pytest", "url": "https://docs.pytest.org/"},
            ],
            "documentation": [
                {"name": "Playwright Docs", "url": "https://playwright.dev/docs/intro"},
                {"name": "Jest Docs", "url": "https://jestjs.io/docs/getting-started"},
                {"name": "Pytest Docs", "url": "https://docs.pytest.org/en/stable/getting-started.html"},
                {"name": "Testing Library Docs", "url": "https://testing-library.com/docs/"},
            ],
        },
        "devops": {
            "tokens": ["devops", "deployment", "systems", "docker", "kubernetes", "ci", "cd", "cloud", "pipeline"],
            "courses": [
                {"name": "Microsoft Learn DevOps", "url": "https://learn.microsoft.com/en-us/training/career-paths/devops-engineer"},
                {"name": "Docker Curriculum", "url": "https://docker-curriculum.com/"},
                {"name": "GitHub Actions Learn", "url": "https://docs.github.com/en/actions/learn-github-actions"},
            ],
            "tools": [
                {"name": "Docker", "url": "https://docs.docker.com/get-started/"},
                {"name": "GitHub Actions", "url": "https://docs.github.com/en/actions"},
                {"name": "Render", "url": "https://render.com/docs"},
            ],
            "documentation": [
                {"name": "Kubernetes Basics", "url": "https://kubernetes.io/docs/tutorials/kubernetes-basics/"},
                {"name": "Twelve-Factor App", "url": "https://12factor.net/"},
                {"name": "CI/CD Guide", "url": "https://about.gitlab.com/topics/ci-cd/"},
                {"name": "Docker Docs", "url": "https://docs.docker.com/"},
            ],
        },
        "security": {
            "tokens": ["security", "auth", "jwt", "oauth", "owasp", "identity", "access control"],
            "courses": [
                {"name": "freeCodeCamp Information Security", "url": "https://www.freecodecamp.org/learn/information-security/"},
                {"name": "OWASP Web Security Testing Guide", "url": "https://owasp.org/www-project-web-security-testing-guide/"},
                {"name": "PortSwigger Web Security Academy", "url": "https://portswigger.net/web-security"},
            ],
            "tools": [
                {"name": "JWT Debugger", "url": "https://jwt.io/"},
                {"name": "OWASP ZAP", "url": "https://www.zaproxy.org/"},
                {"name": "Burp Suite Community", "url": "https://portswigger.net/burp/communitydownload"},
            ],
            "documentation": [
                {"name": "OWASP Top 10", "url": "https://owasp.org/www-project-top-ten/"},
                {"name": "Auth0 JWT Guide", "url": "https://auth0.com/docs/secure/tokens/json-web-tokens"},
                {"name": "OAuth 2.0 Simplified", "url": "https://aaronparecki.com/oauth-2-simplified/"},
                {"name": "MDN Web Security", "url": "https://developer.mozilla.org/en-US/docs/Web/Security"},
            ],
        },
    }
    fallback = {
        "courses": [
            {"name": "CS50x", "url": "https://cs50.harvard.edu/x/"},
            {"name": "The Odin Project", "url": "https://www.theodinproject.com/"},
            {"name": "roadmap.sh", "url": "https://roadmap.sh/"},
        ],
        "tools": [
            {"name": "GitHub", "url": "https://github.com/"},
            {"name": "VS Code", "url": "https://code.visualstudio.com/docs"},
            {"name": "GitHub Skills", "url": "https://skills.github.com/"},
        ],
        "documentation": [
            {"name": "MDN Web Docs", "url": "https://developer.mozilla.org/"},
            {"name": "DevDocs", "url": "https://devdocs.io/"},
            {"name": "Stack Overflow Developer Docs", "url": "https://stackoverflow.blog/"}
        ],
    }

    matched_pack = None
    for key in ["security", "devops", "testing", "backend", "frontend", "data"]:
        if any(token in context for token in category_packs[key]["tokens"]):
            matched_pack = category_packs[key]
            break

    resources = {
        "courses": list((matched_pack or fallback)["courses"]),
        "tools": list((matched_pack or fallback)["tools"]),
        "documentation": list((matched_pack or fallback)["documentation"]),
    }

    has_fcc_resource = any("freecodecamp" in str(item.get("name") or "").lower() for item in resources["courses"])

    if step_type == "Certification" and has_fcc_resource:
        resources["courses"] = resources["courses"][:3] + [
            {"name": "freeCodeCamp Certification Tracks", "url": "https://www.freecodecamp.org/learn/"}
        ]
        resources["documentation"] = resources["documentation"][:3] + [
            {"name": "Certification Planning Guide", "url": "https://www.coursera.org/articles/professional-certificates"}
        ]
    elif step_type == "Certification":
        resources["documentation"] = resources["documentation"][:4]

    return resources


def _coerce_resource_list(items: object) -> list[dict]:
    if not isinstance(items, list):
        return []
    normalized: list[dict] = []
    for item in items:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            url = str(item.get("url") or "").strip()
            if name or url:
                normalized.append({"name": name or url, "url": url or None})
        else:
            text = str(item).strip()
            if text:
                normalized.append({"name": text, "url": None})
    return normalized[:5]


def _ensure_training_path_requirements(steps: list[dict], min_steps: int = 5, max_steps: int = 8) -> list[dict]:
    steps = steps[:max_steps]
    counts = Counter(str(step.get("type") or "Skill") for step in steps)

    filler_templates = {
        "Project": {
            "title": "Build a portfolio-ready full-stack mini-project",
            "description": "Create and deploy a scoped app with frontend, backend API, and persistence to demonstrate job-ready software engineering workflow.",
            "difficulty": "Intermediate",
            "tags": ["project", "fullstack", "software-engineering"],
        },
        "Certification": {
            "title": "Complete one foundational certification track",
            "description": "Take a structured certification path to validate your baseline competency and add verified proof to your portfolio.",
            "difficulty": "Beginner",
            "tags": ["certification", "career", "job-readiness"],
        },
        "Course": {
            "title": "Finish one guided course aligned to your weakest area",
            "description": "Use a structured course to close foundational gaps before taking on larger implementation tasks.",
            "difficulty": "Beginner",
            "tags": ["course", "foundations", "upskilling"],
        },
        "Skill": {
            "title": "Sharpen one core implementation skill",
            "description": "Practice a focused coding skill and apply it immediately in your existing repositories.",
            "difficulty": "Beginner",
            "tags": ["skill", "practice", "portfolio"],
        },
    }

    def append_filler(step_type: str) -> None:
        template = filler_templates[step_type]
        idx = len(steps)
        difficulty = _normalize_difficulty(template["difficulty"])
        xp = _xp_for_difficulty(difficulty, idx)
        tags = list(template["tags"])
        resources = _resource_pack_from_tags(tags, step_type, template["title"], template["description"])
        steps.append(
            {
                "title": template["title"],
                "description": template["description"],
                "reason": template["description"],
                "difficulty": difficulty,
                "reward_xp": xp,
                "estimated_xp": xp,
                "tags": tags,
                "tag": tags[0],
                "type": step_type,
                "resources": resources,
                "ai_explanation": "Recommended to satisfy balanced learning progression and improve employability evidence.",
                "adaptive": {
                    "on_reject": {
                        "title": f"Alternative {step_type} step",
                        "description": "Choose a smaller scoped variant with the same competency target.",
                    },
                    "on_complete": {
                        "next_step": "Advance to the next step in the path.",
                        "next_focus": "Apply the same competency in a more realistic project context.",
                    },
                },
                "progression_logic": "After completion, move to the next difficulty tier for the same domain.",
            }
        )

    while counts["Project"] < 2 and len(steps) < max_steps:
        append_filler("Project")
        counts["Project"] += 1
    while counts["Certification"] < 1 and len(steps) < max_steps:
        append_filler("Certification")
        counts["Certification"] += 1
    while counts["Course"] < 1 and len(steps) < max_steps:
        append_filler("Course")
        counts["Course"] += 1

    while len(steps) < min_steps and len(steps) < max_steps:
        append_filler("Skill")

    return steps[:max_steps]


def _dimension_keywords(dimension_key: str) -> set[str]:
    keyword_map = {
        "frontend_engineering": FRONTEND_LANGS.union(FRAMEWORK_KEYWORDS).union({"ui", "frontend", "web"}),
        "backend_systems_engineering": BACKEND_LANGS.union(BACKEND_KEYWORDS).union({"backend", "service", "api"}),
        "data_science_intelligence": {
            "python",
            "sql",
            "postgresql",
            "mysql",
            "mongodb",
            "pandas",
            "numpy",
            "jupyter",
            "notebook",
            "ml",
            "ai",
            "data",
        },
        "systems_devops_engineering": DEPLOY_KEYWORDS.union({"docker", "kubernetes", "linux", "bash", "powershell", "devops", "ci", "cd"}),
    }
    return keyword_map.get(dimension_key, set())


def _rank_repos_for_dimension(repos: list[dict], dimension_key: str) -> list[dict]:
    keywords = _dimension_keywords(dimension_key)
    ranked: list[tuple[int, dict]] = []
    for repo in repos:
        tokens = _repo_tokens(repo)
        matches = sum(1 for token in tokens if token in keywords)
        commit_count = int(repo.get("commit_count") or 0)
        score = (matches * 10) + min(20, commit_count // 2)
        ranked.append((score, repo))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [repo for _, repo in ranked]


def _repo_context_for_dimension(repos: list[dict], dimension_key: str) -> tuple[list[str], list[str]]:
    ranked = _rank_repos_for_dimension(repos, dimension_key)
    target_repos = ranked[:3] if ranked else []
    repo_names = [str(repo.get("name") or "").strip() for repo in target_repos if str(repo.get("name") or "").strip()]
    tech_signals: list[str] = []
    for repo in target_repos:
        langs = repo.get("languages") or []
        if isinstance(langs, list):
            tech_signals.extend([str(lang) for lang in langs if lang])
        if repo.get("language"):
            tech_signals.append(str(repo.get("language")))
        code_signals = repo.get("code_signals") or {}
        tech_signals.extend([str(framework) for framework in (code_signals.get("frameworks") or []) if framework])
        tech_signals.extend([str(keyword) for keyword in (code_signals.get("keywords") or [])[:6] if keyword])
    unique_signals: list[str] = []
    for signal in tech_signals:
        if signal not in unique_signals:
            unique_signals.append(signal)
    return repo_names[:3], unique_signals[:3]


def generate_personalized_learning_path(
    competency_levels: list[dict],
    repos: list[dict],
    max_steps: int = 8,
) -> list[dict]:
    repo_names = [str(repo.get("name") or "").strip() for repo in repos if str(repo.get("name") or "").strip()]
    top_repo_names = repo_names[:3]
    fallback_evidence = top_repo_names if top_repo_names else ["Repository signals"]
    repo_usage: dict[str, int] = {name: 0 for name in repo_names}

    gaps = identify_skill_gaps(competency_levels)
    gaps = _order_gaps_for_path(gaps, competency_levels)
    steps: list[dict] = []
    candidates_by_gap: list[list[dict]] = []

    def pick_primary_repo(candidates: list[str]) -> str | None:
        pool = [name for name in candidates if name] or repo_names
        if not pool:
            return None
        chosen = min(pool, key=lambda name: (repo_usage.get(name, 0), pool.index(name)))
        repo_usage[chosen] = repo_usage.get(chosen, 0) + 1
        return chosen

    for gap in gaps:
        dimension_key = gap["dimension_key"]
        current_level = gap["current_level"]
        start_index = LEVEL_ORDER.index(current_level)
        progression_levels = LEVEL_ORDER[start_index:]
        priority = gap["priority"]
        dimension_label = gap["dimension"]
        target_repo_names, target_signals = _repo_context_for_dimension(repos, dimension_key)
        gap_candidates: list[dict] = []

        for progression_index, level in enumerate(progression_levels, start=1):
            activity_candidates = COMPETENCY_ACTIVITY_MAP[dimension_key][level]
            for activity in activity_candidates:
                gap_candidates.append(
                    {
                        "activity": activity,
                        "description": (
                            f"{dimension_label} is currently at {current_level}. "
                            f"This task strengthens {level.lower()} competencies and supports outcome-based progression. "
                            "Recommended using your project context."
                        ),
                        "tag": dimension_key,
                        "dimension_key": dimension_key,
                        "tags": [
                            dimension_key,
                            level.lower(),
                            "competency-based",
                            "obe-aligned",
                            "priority-" + priority.lower(),
                        ],
                        "difficulty": level,
                        "reward_xp": _priority_xp(priority, level),
                        "target_repo_names": target_repo_names,
                        "target_signals": target_signals,
                        "priority": priority,
                        "dimension": dimension_label,
                        "competency_level": level,
                        "progression_step": progression_index,
                    }
                )
        if gap_candidates:
            candidates_by_gap.append(gap_candidates)

    while len(steps) < max_steps and any(bucket for bucket in candidates_by_gap):
        for bucket in candidates_by_gap:
            if not bucket or len(steps) >= max_steps:
                continue
            candidate = bucket.pop(0)
            target_repo_names = list(candidate.pop("target_repo_names", []) or [])
            target_signals = list(candidate.pop("target_signals", []) or [])
            primary_repo = pick_primary_repo(target_repo_names)
            title = candidate.pop("activity")
            if primary_repo:
                title = f"{title} ({primary_repo})"
            evidence = (target_repo_names + target_signals)[:3] or fallback_evidence[:3]
            if primary_repo and primary_repo not in evidence:
                evidence = [primary_repo] + evidence
            evidence = evidence[:3]
            candidate["title"] = title
            candidate["evidence"] = evidence
            candidate["description"] = (
                f"{candidate['description']} Context: {', '.join(evidence)}."
            )
            steps.append(candidate)

    return _normalize_steps({"steps": steps[:max_steps]}, max_steps=max_steps)


def _rule_based_learning_path(repos: list[dict], personalization_key: str = "") -> list[dict]:
    if not repos:
        return _normalize_steps(
            {
                "steps": [
                    {
                        "title": "Foundation: Build your first programming project",
                        "description": "No repos found yet. Start with one beginner project so the system can analyze your strengths and weaknesses accurately.",
                        "tag": "programming",
                        "tags": ["programming", "foundation", "beginner"],
                        "difficulty": "Beginner",
                        "reward_xp": 110,
                        "evidence": ["No repository activity detected yet"],
                        "type": "Project",
                    }
                ]
            },
            max_steps=8,
        )

    tokens = set()
    languages: list[str] = []
    total_commits = 0
    for repo in repos:
        tokens.update(_repo_tokens(repo))
        langs = repo.get("languages") or []
        if isinstance(langs, list):
            languages.extend([str(lang).lower() for lang in langs if lang])
        language = repo.get("language")
        if language:
            languages.append(str(language).lower())
        total_commits += int(repo.get("commit_count") or 0)

    lang_counts = Counter(languages)
    sorted_langs = [lang for lang, _ in lang_counts.most_common(3)]
    repo_names = [str(repo.get("name") or "").strip() for repo in repos if str(repo.get("name") or "").strip()]
    top_repos = repo_names[:3]
    has_frontend_lang = any(lang in FRONTEND_LANGS for lang in lang_counts)
    has_backend_lang = any(lang in BACKEND_LANGS for lang in lang_counts)

    has_frontend_framework = any(keyword in tokens for keyword in FRAMEWORK_KEYWORDS)
    has_backend = any(keyword in tokens for keyword in BACKEND_KEYWORDS) or has_backend_lang
    has_database = any(keyword in tokens for keyword in DATABASE_KEYWORDS)
    has_tests = any(keyword in tokens for keyword in TEST_KEYWORDS)
    has_deploy = any(keyword in tokens for keyword in DEPLOY_KEYWORDS)

    def pick_evidence(defaults: list[str]) -> list[str]:
        evidence = top_repos[:2] + sorted_langs[:2]
        if evidence:
            return evidence[:3]
        return defaults[:3]

    steps: list[dict] = []

    if has_frontend_lang and not has_frontend_framework:
        steps.append(
            {
                "title": "Web Development: Build UI using a modern framework",
                "description": "Your repos use JavaScript/TypeScript but show limited framework usage. This strengthens core web engineering outcomes.",
                "tag": "frontend",
                "tags": ["web-development", "frontend", "framework"],
                "evidence": pick_evidence(["JavaScript/TypeScript detected"]),
                "type": "Project",
            }
        )

    if has_frontend_lang and not has_backend:
        steps.append(
            {
                "title": "Software Engineering: Add a backend API layer",
                "description": "Most projects appear frontend-focused. Add REST endpoints and service logic to strengthen software engineering depth.",
                "tag": "backend",
                "tags": ["software-engineering", "backend", "api"],
                "evidence": pick_evidence(["Frontend-heavy repositories"]),
                "type": "Project",
            }
        )

    if not has_database:
        steps.append(
            {
                "title": "Data Management: Design and integrate a real database",
                "description": "No database signals detected. Add schema design and CRUD operations to cover core data management competencies.",
                "tag": "database",
                "tags": ["data-management", "database", "sql"],
                "evidence": pick_evidence(["No SQL/database topics found"]),
                "type": "Skill",
            }
        )

    if not has_tests:
        steps.append(
            {
                "title": "Quality Assurance: Add unit and integration tests",
                "description": "Testing signals are limited. Add automated tests to match software testing and quality outcomes.",
                "tag": "testing",
                "tags": ["testing", "quality-assurance", "software-engineering"],
                "evidence": pick_evidence(["Limited test-related keywords"]),
                "type": "Course",
            }
        )

    if not has_deploy:
        steps.append(
            {
                "title": "Systems and DevOps: Deploy one project end-to-end",
                "description": "Deployment signals are missing. Add CI/CD and production deployment to strengthen systems operations skills.",
                "tag": "deployment",
                "tags": ["systems", "devops", "deployment"],
                "evidence": pick_evidence(["No CI/CD or deployment topics found"]),
                "type": "Project",
            }
        )

    if total_commits < 30:
        steps.append(
            {
                "title": "Study Discipline: Build a consistent commit habit",
                "description": "Low commit volume detected. Consistent weekly commits help document learning progress and project maturity.",
                "tag": "habits",
                "tags": ["version-control", "habits", "portfolio"],
                "evidence": [f"Estimated commits: {total_commits}"],
                "type": "Skill",
            }
        )

    group_scores = {
        "frontend": sum(count for lang, count in lang_counts.items() if lang in FRONTEND_LANGS),
        "backend": sum(count for lang, count in lang_counts.items() if lang in BACKEND_LANGS),
        "data": sum(count for lang, count in lang_counts.items() if lang in {"python", "r", "sql", "jupyter notebook"}),
        "systems": sum(count for lang, count in lang_counts.items() if lang in {"c", "c++", "rust", "go"}),
    }
    strongest_area = max(group_scores, key=group_scores.get) if group_scores else "backend"
    capstone_by_area = {
        "frontend": "Capstone: Build a full frontend product with accessibility and testing",
        "backend": "Capstone: Build a scalable API service with security and testing",
        "data": "Capstone: Build an end-to-end data pipeline and analytics dashboard",
        "systems": "Capstone: Build automation and deployment tooling for a real project",
    }
    steps.append(
        {
            "title": capstone_by_area.get(strongest_area, capstone_by_area["backend"]),
            "description": "Your strongest repo signals should be leveraged for a deeper capstone-level project while continuing curriculum progression.",
            "tag": "capstone",
            "tags": ["capstone", "project-integration", strongest_area],
            "evidence": pick_evidence(["Top repo signals detected"]),
            "type": "Project",
        }
    )

    progression = ["Beginner", "Intermediate", "Advanced"]
    for index, step in enumerate(steps):
        step["difficulty"] = progression[min(index, len(progression) - 1)]
        step["reward_xp"] = 80 + (index * 20)

    if not steps:
        steps = [
            {
                "title": "Advanced Practice: Deepen your strongest stack",
                "description": "Your repos already cover major areas. Focus on an advanced capstone aligned to your strongest technologies.",
                "tag": "advanced",
                "tags": ["advanced", "capstone"],
                "difficulty": "Advanced",
                "reward_xp": 180,
                "evidence": pick_evidence(["Strong cross-domain repo signals"]),
                "type": "Project",
            }
        ]

    # Keep the path grounded in actual repository signals instead of padding it
    # with generic contract filler steps that may not match the student's work.
    steps = _stable_rotate(steps[:8], personalization_key, "main-learning-path")
    return _normalize_steps({"steps": steps}, max_steps=8, enforce_contract=False)


def _rule_based_project_path(
    repo: dict,
    personalization_key: str = "",
    practice_dimensions: list[dict] | None = None,
) -> list[dict]:
    tokens = _repo_tokens(repo)
    langs = []
    if isinstance(repo.get("languages"), list):
        langs.extend([str(lang).lower() for lang in repo.get("languages") if lang])
    if repo.get("language"):
        langs.append(str(repo.get("language")).lower())
    lang_counts = Counter(langs)

    has_frontend_lang = any(lang in FRONTEND_LANGS for lang in lang_counts)
    has_backend_lang = any(lang in BACKEND_LANGS for lang in lang_counts)
    has_frontend_framework = any(keyword in tokens for keyword in FRAMEWORK_KEYWORDS)
    has_backend = any(keyword in tokens for keyword in BACKEND_KEYWORDS) or has_backend_lang
    has_database = any(keyword in tokens for keyword in DATABASE_KEYWORDS)
    has_tests = any(keyword in tokens for keyword in TEST_KEYWORDS)
    has_deploy = any(keyword in tokens for keyword in DEPLOY_KEYWORDS)
    is_data_repo = any(token in tokens for token in {"pandas", "numpy", "dataset", "analysis", "machine", "learning", "ml", "jupyter"})
    is_systems_repo = any(token in tokens for token in {"docker", "kubernetes", "linux", "bash", "powershell", "automation", "infra"})

    def repo_focus() -> str:
        if is_data_repo:
            return "data"
        if is_systems_repo:
            return "systems"
        if has_backend:
            return "backend"
        if has_frontend_lang or has_frontend_framework:
            return "frontend"
        return "general"

    def repo_specific_skill_step(skill_area: str) -> dict:
        focus = repo_focus()
        variants = {
            "database": {
                "frontend": {
                    "title": f"Design app data flow and persistence for {repo_name}",
                    "reason": "This repo looks UI-focused, so the next skill step should connect screens to real stored data.",
                    "tag": "database",
                    "tags": ["skill", "frontend", "database", "state-management"],
                },
                "backend": {
                    "title": f"Model API storage for {repo_name}",
                    "reason": "This repo already leans backend, so add schema design and persistence patterns for its services.",
                    "tag": "database",
                    "tags": ["skill", "backend", "database", "api"],
                },
                "data": {
                    "title": f"Store datasets and outputs cleanly in {repo_name}",
                    "reason": "This repo shows data-oriented signals, so practice managing datasets, results, and reproducible storage.",
                    "tag": "database",
                    "tags": ["skill", "data", "database", "pipeline"],
                },
                "systems": {
                    "title": f"Track configuration and state safely for {repo_name}",
                    "reason": "This repo shows systems signals, so build the skill of managing state, config, and service data correctly.",
                    "tag": "database",
                    "tags": ["skill", "systems", "database", "configuration"],
                },
                "general": {
                    "title": f"Add persistence to {repo_name}",
                    "reason": "No database keywords detected. Add storage for real-world usage.",
                    "tag": "database",
                    "tags": ["skill", "database"],
                },
            },
            "testing": {
                "frontend": {
                    "title": f"Practice UI and interaction testing for {repo_name}",
                    "reason": "This repo looks frontend-heavy, so the skill gap is validating components, forms, and user flows.",
                    "tag": "testing",
                    "tags": ["skill", "frontend", "testing", "quality-assurance"],
                },
                "backend": {
                    "title": f"Practice API and service testing for {repo_name}",
                    "reason": "This repo has backend signals, so focus the skill stage on endpoint and business-logic testing.",
                    "tag": "testing",
                    "tags": ["skill", "backend", "testing", "api"],
                },
                "data": {
                    "title": f"Validate data processing steps in {repo_name}",
                    "reason": "This repo looks data-oriented, so the testing skill should cover data quality and pipeline checks.",
                    "tag": "testing",
                    "tags": ["skill", "data", "testing", "validation"],
                },
                "systems": {
                    "title": f"Verify automation and environment flows in {repo_name}",
                    "reason": "This repo shows systems/devops signals, so the testing skill should target scripts, environments, and pipelines.",
                    "tag": "testing",
                    "tags": ["skill", "systems", "testing", "automation"],
                },
                "general": {
                    "title": f"Write tests for {repo_name}",
                    "reason": "Testing keywords are missing. Add unit/integration tests.",
                    "tag": "testing",
                    "tags": ["skill", "testing"],
                },
            },
            "habits": {
                "frontend": {
                    "title": f"Document UI progress consistently in {repo_name}",
                    "reason": "Use smaller, regular commits so interface work in this repo is easy to track and review.",
                    "tag": "habits",
                    "tags": ["skill", "frontend", "version-control", "habits"],
                },
                "backend": {
                    "title": f"Build a steady backend commit rhythm for {repo_name}",
                    "reason": "Service/API work benefits from frequent commits that isolate routes, logic, and fixes clearly.",
                    "tag": "habits",
                    "tags": ["skill", "backend", "version-control", "habits"],
                },
                "data": {
                    "title": f"Track analysis iterations cleanly in {repo_name}",
                    "reason": "Data work improves when commits clearly separate cleaning, modeling, and reporting changes.",
                    "tag": "habits",
                    "tags": ["skill", "data", "version-control", "habits"],
                },
                "systems": {
                    "title": f"Commit infrastructure changes in smaller steps for {repo_name}",
                    "reason": "Automation and deployment work is easier to debug when commits are incremental and traceable.",
                    "tag": "habits",
                    "tags": ["skill", "systems", "version-control", "habits"],
                },
                "general": {
                    "title": f"Build a consistent commit habit for {repo_name}",
                    "reason": "Low commit volume detected. Consistent weekly commits help document learning progress and project maturity.",
                    "tag": "habits",
                    "tags": ["skill", "version-control", "habits"],
                },
            },
        }
        chosen = variants.get(skill_area, {}).get(focus) or variants.get(skill_area, {}).get("general") or {}
        return {**chosen, "evidence": [repo_name], "type": "Skill"}

    def repo_xp_profile() -> tuple[int, int, str]:
        repo_name = str(repo.get("name") or "").strip()
        signature = sum(ord(ch) for ch in repo_name) % 7
        language_count = len(set(langs))
        signal_count = sum([
            1 if has_frontend_framework else 0,
            1 if has_backend else 0,
            1 if has_database else 0,
            1 if has_tests else 0,
            1 if has_deploy else 0,
        ])
        commit_count = int(repo.get("commit_count") or 0)
        commit_score = min(6, commit_count // 12)
        complexity = language_count + signal_count + commit_score
        base_xp = 105 + min(50, complexity * 5) + signature
        step_bump = 6 + min(4, complexity // 3)
        if complexity >= 10 or commit_count >= 80:
            difficulty = "Advanced"
        elif complexity >= 5 or commit_count >= 25:
            difficulty = "Intermediate"
        else:
            difficulty = "Beginner"
        return base_xp, step_bump, difficulty

    repo_name = repo.get("name") or "this project"
    steps: list[dict] = []

    # Use the account key and weakest detected dimension to select a stable
    # emphasis. Different students can work on the same repo type without
    # receiving identical wording and progression goals.
    variant_seed = f"{personalization_key}:{repo_name}:{_dimension_key_from_label(str((practice_dimensions or [{}])[0].get('label') or ''))}"
    variant = int.from_bytes(hashlib.sha256(variant_seed.encode("utf-8")).digest()[:2], "big") % 3
    emphasis = ["implementation", "quality and edge cases", "portfolio-ready delivery"][variant]

    # Start each repository with a domain milestone before adding the shared
    # quality/deployment stages. This keeps the curriculum consistent while
    # making the path materially different for the kind of product being built.
    domain_step: dict | None = None
    if any(token in tokens for token in {"shop", "store", "cart", "checkout", "ecommerce", "e-commerce", "inventory", "pos"}):
        domain_step = {
            "title": f"Design a reliable product-to-order flow for {repo_name}",
            "reason": "Commerce signals were detected. Strengthen the path by making the core catalog, cart, and order journey explicit and testable.",
            "tag": "product-workflow",
            "tags": ["project", "ecommerce", "product-workflow"],
        }
    elif any(token in tokens for token in {"login", "register", "auth", "authentication", "jwt", "oauth", "rbac", "session"}):
        domain_step = {
            "title": f"Harden authentication and access control in {repo_name}",
            "reason": "Authentication or authorization signals were detected. Focus first on secure identity flows, role boundaries, and protected resources.",
            "tag": "security",
            "tags": ["project", "auth", "security", "rbac"],
        }
    elif any(token in tokens for token in {"dashboard", "analytics", "admin", "management", "reporting", "crm"}):
        domain_step = {
            "title": f"Turn {repo_name} into an evidence-driven dashboard",
            "reason": "Dashboard and analytics signals were detected. Improve the main workflow with clear data states, useful filters, and accessible visual feedback.",
            "tag": "dashboard",
            "tags": ["project", "dashboard", "ui", "data-visualization"],
        }
    elif any(token in tokens for token in {"mobile", "android", "ios", "flutter", "kotlin", "swift", "react-native"}):
        domain_step = {
            "title": f"Build a mobile-first user flow for {repo_name}",
            "reason": "Mobile development signals were detected. Prioritize touch-friendly interaction, device states, and a complete flow that works on smaller screens.",
            "tag": "mobile",
            "tags": ["project", "mobile", "ux", "responsive"],
        }
    elif any(token in tokens for token in {"game", "unity", "pygame", "phaser", "canvas", "gameplay"}):
        domain_step = {
            "title": f"Polish one complete gameplay loop in {repo_name}",
            "reason": "Game-development signals were detected. Create a playable loop with clear input, state changes, feedback, and a restart or progression condition.",
            "tag": "gameplay",
            "tags": ["project", "game", "gameplay", "user-feedback"],
        }
    elif is_data_repo:
        domain_step = {
            "title": f"Make the data workflow reproducible in {repo_name}",
            "reason": "Data and ML signals were detected. Focus on a repeatable pipeline from input data to analysis or model output, with assumptions documented.",
            "tag": "data-pipeline",
            "tags": ["project", "data", "ml", "reproducibility"],
        }
    elif is_systems_repo:
        domain_step = {
            "title": f"Automate a reliable delivery workflow for {repo_name}",
            "reason": "Systems or DevOps signals were detected. Establish a repeatable environment and delivery path with clear logs and recovery steps.",
            "tag": "devops",
            "tags": ["project", "devops", "automation", "reliability"],
        }
    elif has_backend:
        domain_step = {
            "title": f"Define a production-ready API contract for {repo_name}",
            "reason": "Backend signals were detected. Start by making one core API flow explicit through validation, predictable errors, and usable documentation.",
            "tag": "api-design",
            "tags": ["project", "backend", "api", "documentation"],
        }
    elif has_frontend_lang or has_frontend_framework:
        domain_step = {
            "title": f"Create a reusable, accessible feature flow in {repo_name}",
            "reason": "Frontend signals were detected. Strengthen the project around one complete user flow with reusable components and accessible states.",
            "tag": "frontend",
            "tags": ["project", "frontend", "ui", "accessibility"],
        }

    if domain_step:
        domain_step["title"] = f"{domain_step['title']} ({emphasis})"
        domain_step["reason"] = f"{domain_step['reason']} This student's path emphasizes {emphasis}."
        steps.append({
            **domain_step,
            "evidence": [repo_name],
            "type": "Project",
        })

    if has_frontend_lang and not has_frontend_framework:
        steps.append(
            {
                "title": f"Add a frontend framework to {repo_name}",
                "reason": "JavaScript/TypeScript detected but no framework keywords found.",
                "tag": "frontend",
                "tags": ["project", "frontend", "framework"],
                "evidence": [repo_name],
                "type": "Project",
            }
        )
    if has_frontend_lang and not has_backend:
        steps.append(
            {
                "title": f"Create a REST API for {repo_name}",
                "reason": "Looks frontend-focused. Add a backend to showcase full-stack skills.",
                "tag": "backend",
                "tags": ["project", "backend", "api"],
                "evidence": [repo_name],
                "type": "Project",
            }
        )
    if not has_database:
        steps.append(repo_specific_skill_step("database"))
    if not has_tests:
        steps.append(repo_specific_skill_step("testing"))
    if not has_deploy:
        steps.append(
            {
                "title": f"Deploy {repo_name}",
                "reason": "No deployment signals. Publish it to a hosting platform.",
                "tag": "deployment",
                "tags": ["project", "deployment", "devops"],
                "evidence": [repo_name],
                "type": "Project",
            }
        )

    if not steps:
        steps = [
            {
                "title": f"Enhance {repo_name} with advanced features",
                "reason": "Core signals already present. Add performance, security, or scaling improvements.",
                "tag": "advanced",
                "tags": ["project", "advanced", repo_focus()],
                "evidence": [repo_name],
                "type": "Project",
            }
        ]

    base_xp, step_bump, base_difficulty = repo_xp_profile()
    progression = ["Beginner", "Intermediate", "Advanced"]
    start_index = progression.index(base_difficulty)
    for idx, step in enumerate(steps[:5]):
        step["reward_xp"] = max(100, min(200, base_xp + idx * step_bump))
        step["estimated_xp"] = step["reward_xp"]
        step["difficulty"] = progression[min(start_index + idx, len(progression) - 1)]

    if int(repo.get("commit_count") or 0) < 30:
        steps.append(repo_specific_skill_step("habits"))
        steps = steps[:5]
        last_index = min(len(steps) - 1, 4)
        steps[last_index]["reward_xp"] = max(100, min(200, base_xp + last_index * step_bump))
        steps[last_index]["estimated_xp"] = steps[last_index]["reward_xp"]
        steps[last_index]["difficulty"] = progression[min(start_index + last_index, len(progression) - 1)]

    # Keep the repository-domain milestone first so the path teaches the
    # actual product context before the shared quality and delivery work.
    return steps[:5]


def _normalize_steps(payload: dict, max_steps: int = 8, enforce_contract: bool = True) -> list[dict]:
    steps = payload.get("steps") or []
    normalized: list[dict] = []
    for index, item in enumerate(steps):
        title = (item.get("title") or "").strip()
        description = (item.get("description") or item.get("reason") or "").strip()
        if not title or not description:
            continue
        evidence = item.get("evidence") or []
        if isinstance(evidence, str):
            evidence = [evidence]
        if not isinstance(evidence, list):
            evidence = []
        cleaned = []
        for ev in evidence:
            ev = str(ev).strip()
            if ev:
                cleaned.append(ev)
        tags = item.get("tags") or []
        if isinstance(tags, str):
            tags = [tags]
        if not isinstance(tags, list):
            tags = []
        tags_cleaned = []
        for tag in tags:
            tag = str(tag).strip()
            if tag:
                tags_cleaned.append(tag)
        step_type = _normalize_step_type(item.get("type"), title, tags_cleaned)
        difficulty = _normalize_difficulty(item.get("difficulty"))
        xp_raw = item.get("estimated_xp", item.get("reward_xp"))
        xp = None
        if isinstance(xp_raw, (int, float, str)) and str(xp_raw).isdigit():
            xp = int(xp_raw)
        if xp is None:
            xp = _xp_for_difficulty(difficulty, index)
        xp = max(100, min(200, xp))

        resources_raw = item.get("resources") or {}
        if not isinstance(resources_raw, dict):
            resources_raw = {}
        resources = {
            "courses": _coerce_resource_list(resources_raw.get("courses")),
            "tools": _coerce_resource_list(resources_raw.get("tools")),
            "documentation": _coerce_resource_list(resources_raw.get("documentation")),
        }
        if not resources["courses"] and not resources["tools"] and not resources["documentation"]:
            resources = _resource_pack_from_tags(tags_cleaned, step_type, title, description)

        on_reject = item.get("alternative_step") or item.get("on_reject") or {}
        if not isinstance(on_reject, dict):
            on_reject = {}
        on_complete = item.get("next_step") or item.get("on_complete") or {}
        if not isinstance(on_complete, dict):
            on_complete = {}

        ai_explanation = (item.get("ai_explanation") or "").strip()
        if not ai_explanation:
            ai_explanation = (
                "Recommended based on your current skills, weak areas, interests, and repository signals "
                f"to support software engineering progression toward {difficulty.lower()} outcomes."
            )

        progression_logic = (item.get("progression_logic") or "").strip()
        if not progression_logic:
            progression_logic = "When completed, move to the next higher-scope step and apply the skill in a real-world project context."

        normalized.append(
            {
                "title": title,
                "description": description,
                "reason": description,
                "tag": (item.get("tag") or "").strip() or None,
                "evidence": cleaned[:3] if cleaned else None,
                "difficulty": difficulty,
                "reward_xp": xp,
                "estimated_xp": xp,
                "tags": tags_cleaned[:5] if tags_cleaned else None,
                "type": step_type,
                "resources": resources,
                "ai_explanation": ai_explanation,
                "adaptive": {
                    "on_reject": {
                        "title": str(on_reject.get("title") or f"Alternative: {title}").strip(),
                        "description": str(
                            on_reject.get("description")
                            or "Switch to a lighter variant that targets the same competency."
                        ).strip(),
                    },
                    "on_complete": {
                        "next_step": str(
                            on_complete.get("next_step") or "Proceed to the next logical step in the path."
                        ).strip(),
                        "next_focus": str(
                            on_complete.get("next_focus")
                            or "Scale complexity by adding integration, testing, and deployment depth."
                        ).strip(),
                    },
                },
                "progression_logic": progression_logic,
            }
        )
    trimmed = normalized[:max_steps]
    if not enforce_contract:
        return trimmed
    return _ensure_training_path_requirements(trimmed, min_steps=5, max_steps=max_steps)


def _extract_json(content: str) -> dict | None:
    if not content:
        return None
    content = content.strip()
    if content.startswith("{") and content.endswith("}"):
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return None
    match = re.search(r"\{[\s\S]*\}", content)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def build_signal_set(repos: list[dict], include_repo_identity: bool = True) -> set[str]:
    signals: set[str] = set()
    for repo in repos:
        signals.update(_repo_tokens(repo))
        for lang in repo.get("languages") or []:
            signals.add(str(lang).lower())
        if repo.get("language"):
            signals.add(str(repo.get("language")).lower())
        for topic in repo.get("topics") or []:
            signals.add(str(topic).lower())
        if include_repo_identity:
            name = repo.get("name") or ""
            if name:
                signals.add(str(name).lower())
            desc = repo.get("description") or ""
            if desc:
                signals.add(str(desc).lower())
    return signals


def annotate_steps_with_status(steps: list[dict], signals: set[str]) -> tuple[list[dict], int]:
    completed = 0
    total = len(steps) if steps else 0
    updated: list[dict] = []
    for step in steps:
        tags = []
        if step.get("tags"):
            tags.extend([str(tag).lower() for tag in step.get("tags") or []])
        if step.get("tag"):
            tags.append(str(step.get("tag")).lower())
        matched = any(tag in signals for tag in tags)

        status = "done" if matched else "todo"
        if status == "done":
            completed += 1
        updated.append({**step, "status": status})

    progress = int((completed / total) * 100) if total else 0
    return updated, progress


def _derive_learning_profile_from_repos(repos: list[dict], detected_skills: list[str], project_keywords: list[str]) -> dict:
    repo_names = [str(repo.get("name") or "").strip() for repo in repos if str(repo.get("name") or "").strip()]
    tokens: set[str] = set()
    total_commits = 0
    for repo in repos:
        tokens.update(_repo_tokens(repo))
        total_commits += int(repo.get("commit_count") or 0)

    curated_current_skills: list[str] = []
    for skill in detected_skills:
        value = str(skill).strip()
        if value and value not in curated_current_skills:
            curated_current_skills.append(value)
    for token in sorted(tokens):
        if token in {"html", "css", "javascript", "typescript", "python", "java", "sql", "react", "node", "docker"}:
            if token not in curated_current_skills:
                curated_current_skills.append(token)
        if len(curated_current_skills) >= 8:
            break

    missing_skills: list[str] = []
    if not any(token in tokens for token in BACKEND_KEYWORDS):
        missing_skills.append("Backend")
    if not any(token in tokens for token in DATABASE_KEYWORDS):
        missing_skills.append("Databases")
    if not any(token in tokens for token in TEST_KEYWORDS):
        missing_skills.append("Testing")
    if not any(token in tokens for token in DEPLOY_KEYWORDS):
        missing_skills.append("DevOps/Deployment")
    if not missing_skills:
        missing_skills = ["Advanced system design", "Scalability", "Production observability"]

    interests = [str(item).strip() for item in project_keywords if str(item).strip()][:5]
    if not interests:
        interests = ["Software Engineering", "Web Development"]

    if total_commits >= 120 or len(repos) >= 8:
        experience_level = "Advanced"
    elif total_commits >= 35 or len(repos) >= 3:
        experience_level = "Intermediate"
    else:
        experience_level = "Beginner"

    return {
        "current_skills": curated_current_skills or ["HTML", "CSS", "basic JavaScript"],
        "missing_skills": missing_skills,
        "interests": interests,
        "experience_level": experience_level,
        "existing_projects": repo_names[:8] or ["none"],
    }
