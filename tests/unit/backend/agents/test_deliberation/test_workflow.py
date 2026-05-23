"""Deliberation Think Tank workflow YAML — structural assertions (Plan 79 Phase 8).

Source of truth for the 34-node count and sparse-topology pattern.
Asserts the YAML loads under WorkflowSchema (which exercises §8.7
load-time @node.X validation) AND that the deliberation-specific
contract holds: 4 debaters × 3 rounds + 4 critic rounds + proper
sparse-topology wiring.
"""

from __future__ import annotations

from collections import Counter

import pytest
import yaml

from modules.backend.core.config import find_project_root
from modules.backend.schemas.workflow import WorkflowSchema


@pytest.fixture(scope="module")
def workflow() -> WorkflowSchema:
    """Load the think-tank workflow once for the whole test module."""
    path = (
        find_project_root() / "config" / "workflow_templates"
        / "deliberation.think-tank.workflow.yaml"
    )
    with open(path) as f:
        raw = yaml.safe_load(f)
    # Loading exercises §8.7's @node.X step-ID validation. Any typo in
    # a sparse-topology ref or storage step would raise here.
    return WorkflowSchema(**raw)


DEBATER_IDS = ("systems", "quant", "empiricist", "ethicist")


class TestNodeCounts:
    """Plan 79 §15 / Phase 8 acceptance — 34 nodes with the exact
    breakdown 23 agent_step + 7 tool_call + 3 decision + 1 merge."""

    def test_total_step_count(self, workflow):
        assert len(workflow.steps) == 34

    def test_node_type_breakdown(self, workflow):
        counts = Counter(step.node_type for step in workflow.steps)
        assert counts["agent_step"] == 23
        assert counts["tool_call"] == 7
        assert counts["decision"] == 3
        assert counts["merge"] == 1
        # No llm_call or notification — Plan 79 v5 removed both.
        assert counts.get("llm_call", 0) == 0
        assert counts.get("notification", 0) == 0

    def test_named_agent_steps_present(self, workflow):
        ids = {step.id for step in workflow.steps}
        expected_agent = {
            "research", "verify-research",
            "open-systems", "open-quant", "open-empiricist", "open-ethicist",
            "critic-r0",
            "round1-systems", "round1-quant", "round1-empiricist", "round1-ethicist",
            "critic-r1",
            "round2-systems", "round2-quant", "round2-empiricist", "round2-ethicist",
            "critic-r2",
            "round3-systems", "round3-quant", "round3-empiricist", "round3-ethicist",
            "critic-r3",
            "synthesise",
        }
        assert expected_agent.issubset(ids)

    def test_named_tool_calls_present(self, workflow):
        ids = {step.id for step in workflow.steps}
        expected = {
            "halt-bad-research",
            "delta-r1", "delta-r2",
            "store-deliverable-markdown",
            "store-deliverable-json",
            "store-transcript",
            "store-learning",
        }
        assert expected.issubset(ids)

    def test_named_decisions_present(self, workflow):
        ids = {step.id for step in workflow.steps}
        assert {"research-gate", "stop-r1", "stop-r2"}.issubset(ids)

    def test_named_merge_present(self, workflow):
        ids = {step.id for step in workflow.steps}
        assert "final-merge" in ids


class TestCapabilityWiring:
    """Every agent_step references a deliberation.* capability."""

    def test_researcher_capability(self, workflow):
        steps = {s.id: s for s in workflow.steps}
        assert steps["research"].capability == "deliberation.researcher"

    def test_verifier_capability(self, workflow):
        steps = {s.id: s for s in workflow.steps}
        assert steps["verify-research"].capability == "deliberation.research_verifier"

    @pytest.mark.parametrize("debater_id", DEBATER_IDS)
    def test_debater_capabilities_all_rounds(self, workflow, debater_id):
        steps = {s.id: s for s in workflow.steps}
        expected_capability = f"deliberation.debater_{debater_id}"
        for round_name in ("open", "round1", "round2", "round3"):
            step_id = f"{round_name}-{debater_id}"
            assert steps[step_id].capability == expected_capability, (
                f"{step_id} should use {expected_capability}"
            )

    @pytest.mark.parametrize("round_idx", (0, 1, 2, 3))
    def test_critic_capability_all_rounds(self, workflow, round_idx):
        steps = {s.id: s for s in workflow.steps}
        assert steps[f"critic-r{round_idx}"].capability == "deliberation.critic"

    def test_synthesiser_capability(self, workflow):
        steps = {s.id: s for s in workflow.steps}
        assert steps["synthesise"].capability == "deliberation.synthesiser"


class TestSparseTopology:
    """Plan 79 §11 / S2 — each round-N debater step must reference:
    - own_previous: the matching debater's round (N-1) output
    - opponents_previous: a 3-key dict with the OTHER three debaters
    - critic_attack_on_self: the matching debater's attack key only

    A copy-paste bug here poisons the entire deliberation for ~$36 of
    debater calls before anyone notices. This is the most important
    integration assertion in Plan 79."""

    @pytest.mark.parametrize("debater_id", DEBATER_IDS)
    @pytest.mark.parametrize("round_idx,prev_prefix,critic_round", [
        (1, "open", 0),
        (2, "round1", 1),
        (3, "round2", 2),
    ])
    def test_round_n_debater_sparse_topology(
        self, workflow, debater_id, round_idx, prev_prefix, critic_round,
    ):
        steps = {s.id: s for s in workflow.steps}
        step_id = f"round{round_idx}-{debater_id}"
        step = steps[step_id]
        inp = step.input

        # own_previous: own previous-round output.
        expected_own_previous = f"@node.{prev_prefix}-{debater_id}.output"
        assert inp.get("own_previous") == expected_own_previous, (
            f"{step_id}.own_previous wrong: got {inp.get('own_previous')}, "
            f"expected {expected_own_previous}"
        )

        # opponents_previous: the THREE other debaters, mapped to their
        # previous-round outputs. NOT self, NOT duplicates.
        opponents = inp.get("opponents_previous", {})
        expected_opponents = set(DEBATER_IDS) - {debater_id}
        assert set(opponents.keys()) == expected_opponents, (
            f"{step_id}.opponents_previous keys wrong: got {set(opponents.keys())}, "
            f"expected {expected_opponents}"
        )
        for opp_id, ref in opponents.items():
            assert ref == f"@node.{prev_prefix}-{opp_id}.output", (
                f"{step_id}.opponents_previous[{opp_id}] wrong ref: {ref}"
            )

        # critic_attack_on_self: matches the SELF debater id only.
        attack_ref = inp.get("critic_attack_on_self")
        expected_attack = f"@node.critic-r{critic_round}.output.attacks.{debater_id}"
        assert attack_ref == expected_attack, (
            f"{step_id}.critic_attack_on_self wrong: got {attack_ref}, "
            f"expected {expected_attack}"
        )


class TestPersistencePath:
    """Plan 79 §11 — three artifacts must be persisted: Markdown
    deliverable, JSON deliverable, JSON transcript. Plus a learning
    entry. All depend on synthesise."""

    def test_synthesise_depends_on_final_merge(self, workflow):
        steps = {s.id: s for s in workflow.steps}
        assert steps["synthesise"].depends_on == ["final-merge"]

    def test_all_persistence_steps_depend_on_synthesise(self, workflow):
        steps = {s.id: s for s in workflow.steps}
        for persist_id in (
            "store-deliverable-markdown",
            "store-deliverable-json",
            "store-transcript",
            "store-learning",
        ):
            assert "synthesise" in steps[persist_id].depends_on, (
                f"{persist_id} must depend on synthesise"
            )

    def test_markdown_deliverable_references_report_markdown(self, workflow):
        steps = {s.id: s for s in workflow.steps}
        cfg = steps["store-deliverable-markdown"].tool_call_config
        assert cfg.tool_name == "store_artifact"
        # The synthesiser emits report_markdown directly (no Haiku
        # renderer in between) so the schema-validated Markdown
        # survives into storage.
        assert "report_markdown" in cfg.tool_args["content"]
        assert cfg.tool_args["content_type"] == "markdown"

    def test_json_deliverable_uses_standalone_synthesise_ref(self, workflow):
        steps = {s.id: s for s in workflow.steps}
        cfg = steps["store-deliverable-json"].tool_call_config
        assert cfg.tool_name == "store_artifact"
        # Standalone {{@node.synthesise.output}} — Plan 79 §8.6
        # preserves the dict type so §9.1's store_artifact JSON-encodes
        # it for storage with anti-flattening fields intact.
        assert cfg.tool_args["content"].strip() == "{{@node.synthesise.output}}"
        assert cfg.tool_args["content_type"] == "json"
        assert cfg.tool_args["artifact_type"] == "deliberation_deliverable"

    def test_transcript_includes_all_rounds_and_critic_reports(self, workflow):
        steps = {s.id: s for s in workflow.steps}
        cfg = steps["store-transcript"].tool_call_config
        content = cfg.tool_args["content"]
        # The transcript dict must reference all 4 rounds × 4 debaters
        # + 4 critic reports.
        for round_key in ("round_0", "round_1", "round_2", "round_3"):
            assert round_key in content["rounds"]
            assert set(content["rounds"][round_key].keys()) == set(DEBATER_IDS)
        assert set(content["critic_reports"].keys()) == {
            "round_0", "round_1", "round_2", "round_3",
        }


class TestEarlyStopGating:
    """Decision-routing edges + early-stop labels make round 2 / round 3
    optional. The merge then waits over partially-skipped predecessors."""

    def test_stop_r1_has_continue_and_halt_branches(self, workflow):
        steps = {s.id: s for s in workflow.steps}
        opts = {o.key for o in steps["stop-r1"].decision_config.options}
        assert opts == {"continue", "halt"}

    def test_stop_r1_expression_reads_delta_should_continue(self, workflow):
        steps = {s.id: s for s in workflow.steps}
        assert (
            steps["stop-r1"].decision_config.expression
            == "@node.delta-r1.output.should_continue == true"
        )

    def test_research_gate_uses_verifier_passed(self, workflow):
        steps = {s.id: s for s in workflow.steps}
        assert (
            steps["research-gate"].decision_config.expression
            == "@node.verify-research.output.passed == true"
        )

    def test_halt_uses_halt_workflow_tool(self, workflow):
        steps = {s.id: s for s in workflow.steps}
        cfg = steps["halt-bad-research"].tool_call_config
        assert cfg.tool_name == "halt_workflow"
        # Uses issues_text (joined) not issues (list) per S8 fix.
        assert "issues_text" in cfg.tool_args["reason"]
        assert "issues" not in cfg.tool_args["reason"].replace(
            "issues_text", "",
        )

    def test_final_merge_waits_for_all_termination_paths(self, workflow):
        steps = {s.id: s for s in workflow.steps}
        merge = steps["final-merge"]
        assert merge.merge_config.strategy == "wait_all"
        # Must depend on stop-r1, stop-r2, critic-r3 so partially-
        # skipped predecessors (Plan 75 semantics) merge correctly
        # regardless of which round halted.
        assert set(merge.depends_on) == {"stop-r1", "stop-r2", "critic-r3"}


class TestBudgetAndCostCeilings:
    """Plan 79 §6.1 / S6 — synthesise cost ceiling 8.00; workflow
    budget 65.00 covers the worst-case sum of ceilings."""

    def test_workflow_budget_covers_step_ceilings(self, workflow):
        # Realistic worst case: research 5 + verifier 1 + 12 debater
        # ceilings (4 × 3 rounds × 3) + 4 critic ceilings (4 × 3) +
        # synthesiser 8 = 5 + 1 + 36 + 12 + 8 = 62.
        ceilings = sum(
            step.cost_ceiling_usd or 0
            for step in workflow.steps
            if step.node_type == "agent_step"
        )
        assert workflow.budget.max_cost_usd >= ceilings, (
            f"workflow budget {workflow.budget.max_cost_usd} cannot cover "
            f"step ceilings totalling {ceilings}"
        )

    def test_synthesise_ceiling_is_eight(self, workflow):
        steps = {s.id: s for s in workflow.steps}
        # S6 fix — raised from 5.00 to 8.00 to absorb verbose-debater
        # worst-case input.
        assert steps["synthesise"].cost_ceiling_usd == 8.00
