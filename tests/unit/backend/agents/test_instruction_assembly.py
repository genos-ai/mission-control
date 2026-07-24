"""Tests for assemble_instructions with mission brief and user prompt layers."""

from unittest.mock import patch

import pytest

from modules.backend.agents.mission_control.helpers import assemble_instructions


@pytest.fixture
def prompt_tree(tmp_path):
    """Create a temporary prompt directory structure."""
    org_dir = tmp_path / "config" / "prompts" / "organization"
    org_dir.mkdir(parents=True)
    (org_dir / "01_base.md").write_text("Organization base.")

    cat_dir = tmp_path / "config" / "prompts" / "categories"
    cat_dir.mkdir(parents=True)
    (cat_dir / "code.md").write_text("Category: code.")

    agent_dir = tmp_path / "config" / "prompts" / "agents" / "code" / "quality"
    agent_dir.mkdir(parents=True)
    (agent_dir / "system.md").write_text("System: quality agent.")

    return tmp_path


class TestAssembleInstructions:
    def test_base_layers_only(self, prompt_tree):
        with patch(
            "modules.backend.agents.mission_control.helpers.prompt_builder.find_project_root",
            return_value=prompt_tree,
        ):
            result = assemble_instructions("code", "quality")
        assert "Organization base." in result
        assert "Category: code." in result
        assert "System: quality agent." in result
        assert "Mission Brief" not in result
        assert "Mission-Specific Instructions" not in result

    def test_with_mission_brief(self, prompt_tree):
        with patch(
            "modules.backend.agents.mission_control.helpers.prompt_builder.find_project_root",
            return_value=prompt_tree,
        ):
            result = assemble_instructions(
                "code",
                "quality",
                mission_brief="Build a secure API",
            )
        assert "## Mission Brief" in result
        assert "Build a secure API" in result

    def test_with_user_prompt(self, prompt_tree):
        with patch(
            "modules.backend.agents.mission_control.helpers.prompt_builder.find_project_root",
            return_value=prompt_tree,
        ):
            result = assemble_instructions(
                "code",
                "quality",
                user_prompt="Focus on SQL injection prevention",
            )
        assert "## Mission-Specific Instructions" in result
        assert "SQL injection prevention" in result

    def test_all_layers(self, prompt_tree):
        with patch(
            "modules.backend.agents.mission_control.helpers.prompt_builder.find_project_root",
            return_value=prompt_tree,
        ):
            result = assemble_instructions(
                "code",
                "quality",
                mission_brief="Build secure API",
                user_prompt="Focus on auth",
            )
        parts = result.split("\n\n")
        org_idx = next(i for i, p in enumerate(parts) if "Organization base" in p)
        brief_idx = next(i for i, p in enumerate(parts) if "Mission Brief" in p)
        user_idx = next(i for i, p in enumerate(parts) if "Mission-Specific" in p)
        assert org_idx < brief_idx < user_idx

    def test_missing_category_and_agent(self, prompt_tree):
        with patch(
            "modules.backend.agents.mission_control.helpers.prompt_builder.find_project_root",
            return_value=prompt_tree,
        ):
            result = assemble_instructions("nonexistent", "agent")
        assert "Organization base." in result
        assert "nonexistent" not in result
