from app.services import inference


def test_infer_learning_path_uses_flan_then_llm_enhancer(monkeypatch):
    flan_steps = [
        {
            "title": "FLAN repo plan",
            "description": "Use repository evidence to improve demo-repo.",
            "reason": "Generated from trained model output.",
            "evidence": ["demo-repo"],
        },
        {
            "title": "FLAN repo docs",
            "description": "Document the demo-repo implementation.",
            "reason": "Generated from trained model output.",
            "evidence": ["demo-repo"],
        },
        {
            "title": "FLAN repo tests",
            "description": "Add test proof for demo-repo.",
            "reason": "Generated from trained model output.",
            "evidence": ["demo-repo"],
        },
    ]
    refined_steps = [
        {
            "title": "LLM refined repo plan",
            "description": "Polish the trained-model plan for demo-repo.",
            "reason": "Enhanced from trained model output.",
            "evidence": ["demo-repo"],
        },
        {
            "title": "LLM refined repo docs",
            "description": "Polish documentation guidance for demo-repo.",
            "reason": "Enhanced from trained model output.",
            "evidence": ["demo-repo"],
        },
        {
            "title": "LLM refined repo tests",
            "description": "Polish testing guidance for demo-repo.",
            "reason": "Enhanced from trained model output.",
            "evidence": ["demo-repo"],
        },
    ]
    captured = {}

    def fake_flan_learning_path(model, repos, detected_skills=None, project_keywords=None, practice_dimensions=None):
        captured["flan_model"] = model
        captured["repos"] = repos
        captured["practice_dimensions"] = practice_dimensions
        return flan_steps

    def fake_refine_learning_steps(steps, repos):
        captured["refiner_input"] = steps
        return refined_steps

    monkeypatch.setattr(inference.flan_t5, "infer_learning_path", fake_flan_learning_path)
    monkeypatch.setattr(inference.llm_refiner, "is_enabled", lambda: True)
    monkeypatch.setattr(inference.llm_refiner, "refine_learning_steps", fake_refine_learning_steps)

    result = inference.infer_learning_path(
        [{"name": "demo-repo", "language": "TypeScript"}],
        practice_dimensions=[{"label": "Testing", "confidence": 35, "evidence": ["No tests"]}],
    )

    assert result[0]["title"] == "LLM refined repo plan"
    assert captured["refiner_input"][0]["title"] == "FLAN repo plan"
    assert captured["practice_dimensions"][0]["label"] == "Testing"


def test_infer_project_learning_paths_uses_flan_for_all_repos(monkeypatch):
    captured = {}

    def fake_flan_project_learning_paths(
        model,
        repos,
        detected_skills=None,
        project_keywords=None,
        practice_dimensions=None,
    ):
        captured["repos_count"] = len(repos)
        return [
            {
                "repo_name": repo["name"],
                "steps": [
                    {
                        "title": f"FLAN path for {repo['name']}",
                        "description": "Repository-specific trained model output.",
                        "reason": "Repository-specific trained model output.",
                        "evidence": [repo["name"]],
                    },
                    {
                        "title": f"Document {repo['name']}",
                        "description": "Add README evidence.",
                        "reason": "Add README evidence.",
                        "evidence": [repo["name"]],
                    },
                    {
                        "title": f"Test {repo['name']}",
                        "description": "Add quality proof.",
                        "reason": "Add quality proof.",
                        "evidence": [repo["name"]],
                    },
                ],
            }
            for repo in repos
        ]

    monkeypatch.setattr(inference.flan_t5, "infer_project_learning_paths", fake_flan_project_learning_paths)
    monkeypatch.setattr(inference.llm_refiner, "is_enabled", lambda: False)

    repos = [{"name": f"repo-{index}", "language": "TypeScript"} for index in range(10)]

    result = inference.infer_project_learning_paths(repos, practice_dimensions=[])

    assert len(result) == 10
    assert captured["repos_count"] == 10
    titles = [step["title"] for step in result[0]["steps"]]
    assert "FLAN path for repo-0" in titles


def test_infer_project_learning_paths_lets_llm_enhance_flan_output(monkeypatch):
    def fake_flan_project_learning_paths(*args, **kwargs):
        return [
            {
                "repo_name": "demo-repo",
                "steps": [
                    {
                        "title": "FLAN generated base stage",
                        "description": "Use repository evidence to create a distinct repo milestone.",
                        "reason": "Generated from trained model output.",
                        "tag": "base-stage",
                        "tags": ["base-stage"],
                        "evidence": ["demo-repo"],
                    },
                    {
                        "title": "Document demo-repo",
                        "description": "Add README proof.",
                        "reason": "Add README proof.",
                        "evidence": ["demo-repo"],
                    },
                    {
                        "title": "Test demo-repo",
                        "description": "Add quality proof.",
                        "reason": "Add quality proof.",
                        "evidence": ["demo-repo"],
                    },
                ],
            }
        ]

    def fake_generate_project_learning_paths(*args, **kwargs):
        return [
            {
                "repo_name": "demo-repo",
                "steps": [
                    {
                        "title": "LLM generated unique stage",
                        "description": "Use model scores to create a distinct repo milestone.",
                        "reason": "Generated from FLAN-T5 score signals.",
                        "tag": "unique-stage",
                        "tags": ["unique-stage"],
                        "evidence": ["demo-repo"],
                    },
                    {
                        "title": "LLM generated documentation stage",
                        "description": "Create a clearer repo proof bundle.",
                        "reason": "Enhanced from trained model output.",
                        "tag": "docs-stage",
                        "tags": ["docs-stage"],
                        "evidence": ["demo-repo"],
                    },
                    {
                        "title": "LLM generated testing stage",
                        "description": "Create a clearer quality proof bundle.",
                        "reason": "Enhanced from trained model output.",
                        "tag": "testing-stage",
                        "tags": ["testing-stage"],
                        "evidence": ["demo-repo"],
                    },
                ],
            }
        ]

    monkeypatch.setattr(inference.flan_t5, "infer_project_learning_paths", fake_flan_project_learning_paths)
    monkeypatch.setattr(inference.llm_refiner, "is_enabled", lambda: True)
    monkeypatch.setattr(inference.llm_refiner, "generate_project_learning_paths", fake_generate_project_learning_paths)

    result = inference.infer_project_learning_paths([{"name": "demo-repo", "language": "TypeScript"}])

    titles = [step["title"] for step in result[0]["steps"]]
    assert "LLM generated unique stage" in titles


def test_infer_project_learning_paths_falls_back_when_flan_fails(monkeypatch):
    def fake_flan_project_learning_paths(*args, **kwargs):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(inference.flan_t5, "infer_project_learning_paths", fake_flan_project_learning_paths)
    monkeypatch.setattr(inference.llm_refiner, "is_enabled", lambda: False)

    result = inference.infer_project_learning_paths([{"name": "demo-repo", "language": "TypeScript"}])

    assert result[0]["repo_name"] == "demo-repo"
    assert len(result[0]["steps"]) >= 3


def test_infer_learning_path_uses_llm_when_flan_fails(monkeypatch):
    captured = {}

    def fake_flan_fail(*args, **kwargs):
        raise RuntimeError("flan timeout")

    def fake_generate_steps(*args, **kwargs):
        captured["called"] = True
        return [
            {
                "title": "LLM fallback rescue plan",
                "description": "Rescue plan tailored to repo.",
                "reason": "Tailored to repo.",
                "evidence": ["demo-repo"],
            },
            {
                "title": "LLM fallback rescue docs",
                "description": "Rescue docs tailored to repo.",
                "reason": "Tailored to repo.",
                "evidence": ["demo-repo"],
            },
            {
                "title": "LLM fallback rescue tests",
                "description": "Rescue tests tailored to repo.",
                "reason": "Tailored to repo.",
                "evidence": ["demo-repo"],
            },
        ]

    monkeypatch.setattr(inference.flan_t5, "infer_learning_path", fake_flan_fail)
    monkeypatch.setattr(inference.llm_refiner, "is_enabled", lambda: True)
    monkeypatch.setattr(inference.llm_refiner, "generate_learning_path_steps", fake_generate_steps)

    result = inference.infer_learning_path([{"name": "demo-repo", "language": "Python"}])

    assert captured.get("called") is True
    assert result[0]["title"] == "LLM fallback rescue plan"


def test_infer_project_learning_paths_uses_llm_when_flan_fails(monkeypatch):
    captured = {}

    def fake_flan_fail(*args, **kwargs):
        raise RuntimeError("flan timeout")

    def fake_generate_projects(*args, **kwargs):
        captured["called"] = True
        return [
            {
                "repo_name": "demo-repo",
                "steps": [
                    {
                        "title": "LLM project rescue stage 1",
                        "description": "Stage 1.",
                        "reason": "Stage 1 reason.",
                        "evidence": ["demo-repo"],
                    },
                    {
                        "title": "LLM project rescue stage 2",
                        "description": "Stage 2.",
                        "reason": "Stage 2 reason.",
                        "evidence": ["demo-repo"],
                    },
                    {
                        "title": "LLM project rescue stage 3",
                        "description": "Stage 3.",
                        "reason": "Stage 3 reason.",
                        "evidence": ["demo-repo"],
                    },
                ],
            }
        ]

    monkeypatch.setattr(inference.flan_t5, "infer_project_learning_paths", fake_flan_fail)
    monkeypatch.setattr(inference.llm_refiner, "is_enabled", lambda: True)
    monkeypatch.setattr(inference.llm_refiner, "generate_project_learning_paths", fake_generate_projects)

    result = inference.infer_project_learning_paths([{"name": "demo-repo", "language": "Python"}])

    assert captured.get("called") is True
    titles = [s["title"] for s in result[0]["steps"]]
    assert "LLM project rescue stage 1" in titles

