from app.services.github import dedupe_repo_summaries


def test_dedupe_repo_summaries_keeps_one_row_per_repo_name():
    summaries = [
        {"name": "Portfolio", "commit_count": 1, "stars": 0},
        {"name": "portfolio", "commit_count": 8, "stars": 1},
        {"name": "API", "commit_count": 2, "stars": 0},
        {"name": " ", "commit_count": 99, "stars": 99},
    ]

    result = dedupe_repo_summaries(summaries)

    assert [item["name"] for item in result] == ["portfolio", "API"]
    assert result[0]["commit_count"] == 8
