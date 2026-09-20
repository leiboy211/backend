import datetime as dt
import time
import requests


GITHUB_API = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"
GITHUB_USER_AGENT = "DevPath-Portfolio/1.0"


def _github_headers(token: str | None = None) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
        "User-Agent": GITHUB_USER_AGENT,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _request_with_retry(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict | None = None,
    data: dict | None = None,
    timeout: int = 15,
    retries: int = 2,
) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                data=data,
                timeout=timeout,
            )
            if response.status_code in {502, 503, 504} and attempt < retries:
                time.sleep(0.4 * (attempt + 1))
                continue
            return response
        except requests.RequestException as exc:
            last_error = exc
            if attempt >= retries:
                raise
            time.sleep(0.4 * (attempt + 1))
    if last_error:
        raise last_error
    raise RuntimeError("Unknown HTTP retry failure")


def exchange_code_for_token(client_id: str, client_secret: str, code: str, redirect_uri: str) -> str:
    response = _request_with_retry(
        "POST",
        "https://github.com/login/oauth/access_token",
        headers={"Accept": "application/json", "User-Agent": GITHUB_USER_AGENT},
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        },
        timeout=15,
        retries=1,
    )
    response.raise_for_status()
    payload = response.json()
    token = payload.get("access_token")
    if not token:
        error = payload.get("error", "unknown_error")
        description = payload.get("error_description", "No access_token returned from GitHub.")
        raise ValueError(f"GitHub OAuth failed: {error} - {description}")
    return token


def fetch_github_user(token: str) -> dict:
    response = _request_with_retry(
        "GET",
        f"{GITHUB_API}/user",
        headers=_github_headers(token),
        timeout=15,
        retries=2,
    )
    response.raise_for_status()
    return response.json()


def fetch_repo_languages(token: str, full_name: str) -> list[str]:
    response = _request_with_retry(
        "GET",
        f"{GITHUB_API}/repos/{full_name}/languages",
        headers=_github_headers(token),
        timeout=15,
        retries=1,
    )
    if response.status_code != 200:
        return []
    payload = response.json()
    if not isinstance(payload, dict):
        return []
    return list(payload.keys())


def fetch_repo_language_bytes(token: str, full_name: str) -> dict[str, int]:
    response = _request_with_retry(
        "GET",
        f"{GITHUB_API}/repos/{full_name}/languages",
        headers=_github_headers(token),
        timeout=15,
        retries=1,
    )
    if response.status_code != 200:
        return {}
    payload = response.json()
    if not isinstance(payload, dict):
        return {}
    result: dict[str, int] = {}
    for key, value in payload.items():
        name = str(key or "").strip()
        if not name:
            continue
        try:
            result[name] = int(value or 0)
        except (TypeError, ValueError):
            continue
    return result


def fetch_public_repo_languages(full_name: str) -> list[str]:
    response = _request_with_retry(
        "GET",
        f"{GITHUB_API}/repos/{full_name}/languages",
        headers=_github_headers(),
        timeout=15,
        retries=1,
    )
    if response.status_code != 200:
        return []
    payload = response.json()
    if not isinstance(payload, dict):
        return []
    return list(payload.keys())


def fetch_public_repo_language_bytes(full_name: str) -> dict[str, int]:
    response = _request_with_retry(
        "GET",
        f"{GITHUB_API}/repos/{full_name}/languages",
        headers=_github_headers(),
        timeout=15,
        retries=1,
    )
    if response.status_code != 200:
        return {}
    payload = response.json()
    if not isinstance(payload, dict):
        return {}
    result: dict[str, int] = {}
    for key, value in payload.items():
        name = str(key or "").strip()
        if not name:
            continue
        try:
            result[name] = int(value or 0)
        except (TypeError, ValueError):
            continue
    return result


def fetch_repos(token: str, max_pages: int | None = None) -> list[dict]:
    repos = []
    page = 1
    while True:
        if max_pages is not None and page > max_pages:
            break
        response = _request_with_retry(
            "GET",
            f"{GITHUB_API}/user/repos",
            headers=_github_headers(token),
            params={"per_page": 100, "page": page, "sort": "updated"},
            timeout=20,
            retries=1,
        )
        response.raise_for_status()
        page_data = response.json()
        repos.extend(page_data)
        if len(page_data) < 100:
            break
        page += 1
    return repos


def fetch_public_repos(username: str, max_pages: int | None = None) -> list[dict]:
    repos = []
    page = 1
    while True:
        if max_pages is not None and page > max_pages:
            break
        response = _request_with_retry(
            "GET",
            f"{GITHUB_API}/users/{username}/repos",
            headers=_github_headers(),
            params={"per_page": 100, "page": page, "sort": "updated", "type": "owner"},
            timeout=20,
            retries=1,
        )
        response.raise_for_status()
        page_data = response.json()
        repos.extend(page_data)
        if len(page_data) < 100:
            break
        page += 1
    return repos


def dedupe_repo_summaries(summaries: list[dict]) -> list[dict]:
    deduped: dict[str, dict] = {}
    for summary in summaries:
        repo_name = str(summary.get("name") or "").strip()
        if not repo_name:
            continue
        key = repo_name.lower()
        existing = deduped.get(key)
        if existing is None:
            deduped[key] = summary
            continue
        existing_commits = int(existing.get("commit_count") or 0)
        next_commits = int(summary.get("commit_count") or 0)
        existing_stars = int(existing.get("stars") or 0)
        next_stars = int(summary.get("stars") or 0)
        if (next_commits, next_stars) > (existing_commits, existing_stars):
            deduped[key] = summary
    return list(deduped.values())


def fetch_repo_commit_count(full_name: str, username: str, token: str | None = None, max_pages: int = 5) -> int:
    if not full_name:
        return 0
    headers = _github_headers(token)

    # Prefer contributors API: it returns contribution totals per user for this repo.
    contributors_response = _request_with_retry(
        "GET",
        f"{GITHUB_API}/repos/{full_name}/contributors",
        headers=headers,
        params={"per_page": 100, "anon": "1"},
        timeout=20,
        retries=1,
    )
    if contributors_response.status_code == 200:
        contributors = contributors_response.json()
        if isinstance(contributors, list):
            target = username.lower()
            for contributor in contributors:
                login = str(contributor.get("login") or "").lower()
                if login == target:
                    try:
                        return int(contributor.get("contributions") or 0)
                    except (TypeError, ValueError):
                        return 0

    # Fallback: paginate all commits when contributors endpoint is unavailable.
    total = 0
    for page in range(1, max_pages + 1):
        response = _request_with_retry(
            "GET",
            f"{GITHUB_API}/repos/{full_name}/commits",
            headers=headers,
            params={"per_page": 100, "page": page},
            timeout=20,
            retries=1,
        )
        if response.status_code == 409:
            # Empty repository
            return total
        if response.status_code != 200:
            return total
        page_data = response.json()
        if not isinstance(page_data, list):
            return total
        total += len(page_data)
        if len(page_data) < 100:
            break
    return total


def fetch_commit_streak_days(username: str, token: str | None = None, max_pages: int = 10) -> int:
    if not username:
        return 0
    headers = _github_headers(token)

    commit_days: set[str] = set()
    for page in range(1, max_pages + 1):
        events_url = f"{GITHUB_API}/users/{username}/events" if token else f"{GITHUB_API}/users/{username}/events/public"
        response = _request_with_retry(
            "GET",
            events_url,
            headers=headers,
            params={"per_page": 100, "page": page},
            timeout=20,
            retries=1,
        )
        if response.status_code != 200:
            break
        events = response.json()
        if not isinstance(events, list) or not events:
            break
        for event in events:
            if event.get("type") != "PushEvent":
                continue
            created_at = event.get("created_at")
            if created_at:
                commit_days.add(str(created_at)[:10])
        if len(events) < 100:
            break

    if not commit_days:
        return 0

    today = dt.datetime.now(dt.timezone.utc).date()
    start_day = today if today.isoformat() in commit_days else today - dt.timedelta(days=1)
    streak = 0
    cursor = start_day
    while cursor.isoformat() in commit_days:
        streak += 1
        cursor -= dt.timedelta(days=1)
    return streak


def summarize_repo(
    raw_repo: dict,
    languages: list[str],
    commit_count: int = 0,
    language_bytes: dict[str, int] | None = None,
    code_signals: dict | None = None,
) -> dict:
    last_push = raw_repo.get("pushed_at")
    last_push_dt = dt.datetime.fromisoformat(last_push.replace("Z", "+00:00")) if last_push else None
    merged_languages: list[str] = []
    for value in [*(languages or []), *list((language_bytes or {}).keys()), raw_repo.get("language")]:
        clean = str(value or "").strip()
        if clean and clean not in merged_languages:
            merged_languages.append(clean)
    primary_language = raw_repo.get("language")
    if not primary_language and merged_languages:
        primary_language = merged_languages[0]
    return {
        "name": raw_repo.get("name"),
        "description": raw_repo.get("description"),
        "language": primary_language,
        "languages": merged_languages,
        "language_bytes": language_bytes or {},
        "stars": raw_repo.get("stargazers_count", 0),
        "topics": raw_repo.get("topics", []),
        "code_signals": code_signals or {},
        "last_push": last_push_dt.isoformat() if last_push_dt else None,
        "commit_count": commit_count,
    }
