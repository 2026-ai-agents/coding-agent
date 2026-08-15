"""도구의 약속: 파일은 쓰이고, 이력은 남고, 남의 파일은 못 건드린다."""

from agent import scaffold


def test_reset_lays_the_skeleton(project):
    files = project.list_files()
    assert "Dockerfile" in files and "docker-compose.yml" in files
    assert "app.py" in files and "static/index.html" in files
    assert project.git("log", "--oneline")[1].endswith("Scaffold the product skeleton")


def test_infrastructure_is_not_written_by_the_model():
    """Dockerfile·compose·requirements는 골격이 준다. 매번 흔들릴 이유가 없다."""
    owned = {path for paths in scaffold.OWNERSHIP.values() for path in paths}
    assert "Dockerfile" not in owned and "docker-compose.yml" not in owned
    assert "requirements.txt" not in owned


def test_roles_do_not_share_files():
    """소유권이 겹치지 않으므로 병렬로 써도 충돌할 수 없다."""
    paths = [path for paths in scaffold.OWNERSHIP.values() for path in paths]
    assert len(paths) == len(set(paths))


def test_branch_and_commit_leave_a_trail(project):
    project.branch("feature/backend")
    project.write_file("app.py", "# 백엔드\n")
    sha = project.commit("backend: 구현")
    assert sha and "feature/backend" in project.git("branch", "--show-current")[1]
    assert "backend: 구현" in project.graph()


def test_merge_brings_branches_into_main(project):
    for role, path in (("backend", "app.py"), ("frontend", "static/index.html")):
        project.branch(f"feature/{role}")
        project.write_file(path, f"# {role}\n")
        project.commit(f"{role}: 구현")
        project.git("checkout", "-q", "main")

    merged, log = project.merge(["feature/backend", "feature/frontend"])
    assert merged and log.count("머지") == 2
    assert project.read_file("app.py").strip() == "# backend"


def test_tests_run_against_the_generated_project(project):
    project.write_file("tests/test_smoke.py", "def test_ok():\n    assert 1 + 1 == 2\n")
    passed, output = project.run_tests()
    assert passed and "1 passed" in output


def test_failing_tests_come_back_with_the_log(project):
    project.write_file("tests/test_smoke.py", "def test_no():\n    assert False\n")
    passed, output = project.run_tests()
    assert not passed and "assert" in output


def test_status_round_trips(project):
    project.save_status({"state": "running", "tasks": [], "events": [], "cost": {}})
    assert project.load_status()["state"] == "running"
