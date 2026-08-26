from app.services import inference


def test_infer_project_learning_paths_includes_all_repos(monkeypatch):
    captured = {}

    def fake_generate_project_learning_paths(
        *,
        repos,
        practice_dimensions=None,
        fallback_projects,
        max_projects=None,
        max_steps_per_project=5,
        personalization_key="",
    ):
        captured["repos_count"] = len(repos)
        captured["fallback_count"] = len(fallback_projects)
        captured["max_projects"] = max_projects
        return fallback_projects

    monkeypatch.setattr(inference.llm_refiner, "generate_project_learning_paths", fake_generate_project_learning_paths)

    repos = [{"name": f"repo-{index}", "language": "TypeScript"} for index in range(10)]

    result = inference.infer_project_learning_paths(repos, practice_dimensions=[])

    assert len(result) == 10
    assert captured["repos_count"] == 10
    assert captured["fallback_count"] == 10
    assert captured["max_projects"] == 10
