"""Unit tests for the agent YAML file locator shared by the seeder, registry and sync."""

from modules.backend.core.agent_files import (
    AGENT_FILE_NAME,
    agents_dir,
    find_agent_files,
)


def test_the_agents_directory_is_under_the_project_config(tmp_path):
    assert agents_dir(tmp_path) == tmp_path / "config" / "agents"


def test_agent_files_are_found_at_any_depth_in_a_stable_order(tmp_path):
    base = agents_dir(tmp_path)
    for relative in ["b/two", "a/one", "a/nested/three"]:
        (base / relative).mkdir(parents=True)
        (base / relative / AGENT_FILE_NAME).write_text("agent_name: x\n")

    found = [path.relative_to(base).as_posix() for path in find_agent_files(tmp_path)]

    assert found == ["a/nested/three/agent.yaml", "a/one/agent.yaml", "b/two/agent.yaml"]


def test_other_files_are_not_agent_files(tmp_path):
    base = agents_dir(tmp_path) / "a"
    base.mkdir(parents=True)
    (base / "notes.yaml").write_text("x: 1\n")
    (base / AGENT_FILE_NAME).write_text("agent_name: x\n")

    assert [p.name for p in find_agent_files(tmp_path)] == [AGENT_FILE_NAME]


def test_a_missing_directory_has_no_agent_files(tmp_path):
    assert find_agent_files(tmp_path) == []
