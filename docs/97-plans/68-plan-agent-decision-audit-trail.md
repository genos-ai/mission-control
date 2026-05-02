# Plan 68 — Agent Decision Audit Trail

**Status:** Future enhancement
**Priority:** High — regulatory prerequisite for Tier 3-4 agent production use
**Depends on:** Plan 51 (supervisor circuit breakers), Plan 45 (workflow model), WASA spec (66)
**Control objectives addressed:** 6.4 (audit trail), 6.5 (memory integrity), 6.6 (circuit breakers)

---

## Problem

The platform has good operational logging — events, LLM call costs, supervisor decisions, Langfuse traces. What it lacks is a **decision audit trail**: a tamper-resistant, replayable record of each consequential agent action that captures not just what happened, but the full chain that led to it.

The gap is regulatory and architectural:

- **Regulatory:** BCBS 239 requires accuracy and integrity of risk data for decisions touching regulated outputs. EU AI Act Art. 12 requires documentation of AI system decisions. Neither is satisfied by structlog JSONL files that rotate at 10MB with no integrity protection.
- **Architectural:** When an agent takes a consequential action — approving a finding, executing an exploit, advancing a multi-wave plan — the question "why did it do that?" must be answerable from the log alone, without access to the original system, weeks or months later.

Concretely, an auditor needs to reconstruct: what was the agent asked to do → what did it reason → what tools did it call and what came back → what did it decide → did that match the intent. That chain does not exist in one place today.

---

## Context: What Already Exists

This plan extends, not replaces, existing infrastructure:

| Existing mechanism | What it captures | What it misses |
|---|---|---|
| `execution_decisions` table | Supervisor decisions with decision_type and reason string | Alternatives considered; structured reasoning; tool invocations |
| `llm_calls` table | Token counts, cost, model, agent attribution | Prompt content, tool results, output at decision time |
| Langfuse traces | Full token streams, tool call sequences, latencies | Structured query access; tamper resistance; long-term retention |
| Platform event bus | All mission/session events persisted by default | No integrity protection; no chain linkage across events |
| WASA audit events (§2.7.9) | 14 typed events with structured payloads | No decision-chain linkage; no reasoning capture; no output snapshot |

The gap is not volume — we log plenty. The gap is **structure** (reasoning is a string, not a queryable chain), **integrity** (any admin can UPDATE rows), and **completeness** (the chain from intent to outcome is not captured as a unit).

---

## Design

### Core Concept: AgentDecisionRecord

A single database record that captures one consequential agent action as a complete, self-contained unit. Not a stream of events — a record that tells the full story of one decision.

```
What was the agent asked to do?  →  intent
What did it reason?              →  thinking
What tools did it call?          →  tool_invocations
What did it decide?              →  output  (snapshot at decision time)
Did that match the intent?       →  outcome
What went wrong?                 →  error
```

This record is the unit of audit. An auditor selects a sample of consequential actions and reconstructs each one from its `AgentDecisionRecord` alone.

### What "consequential" means

Not every agent action warrants a full decision record. The trigger is **tier and action type**:

| Tier | Examples | Decision record? |
|---|---|---|
| Tier 1-2 | CRUD operations, read-only queries, summaries | No — operational logs sufficient |
| Tier 3 | Supervisor advance/escalate/refine decisions, WASA triage verdicts, WASA exploit tool calls | Yes |
| Tier 4 | Any action that modifies external state: exploit execution, destructive tool calls, multi-wave plan advancement in autonomous mode | Yes — full output snapshot required |

The platform's existing `ExploitStage` enum in WASA and the `GateMode` enum on workflow steps are the natural tier markers. Mission Control injects the decision record at the harness level — agents do not write their own records.

---

## Data Model

```python
# modules/backend/models/agent_decision.py

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import (
    BigInteger, Boolean, DateTime, Enum as SAEnum,
    ForeignKey, Index, Integer, String, Text, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from modules.backend.models.base import Base


class DecisionTier(str, Enum):
    TIER_3 = "TIER_3"    # consequential: supervisor decisions, triage verdicts
    TIER_4 = "TIER_4"    # high-consequence: external state modification, autonomous advancement


class DecisionOutcome(str, Enum):
    SUCCESS = "SUCCESS"          # output matched intent; completed without error
    PARTIAL = "PARTIAL"          # completed with degraded output (e.g. partial findings)
    FAILED = "FAILED"            # error prevented completion
    ESCALATED = "ESCALATED"      # halted by circuit breaker or human gate
    SUPERSEDED = "SUPERSEDED"    # decision was overridden by a later decision or human


class AgentDecisionRecord(Base):
    """
    Tamper-resistant record of one consequential agent decision.

    Append-only. The application database user has INSERT privilege only —
    no UPDATE, no DELETE. Integrity is verified by a SHA-256 hash chain:
    each record hashes its own content + the previous record's chain_hash,
    forming a chain that detects any gap or modification.

    An auditor reconstructs the complete decision chain by reading all records
    for a mission_id ordered by sequence_number, verifying the hash chain,
    and reading the structured fields — without access to the live system.
    """
    __tablename__ = "agent_decision_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    record_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    # Chain fields
    mission_id: Mapped[str] = mapped_column(String(36), ForeignKey("missions.id"), nullable=False)
    session_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    execution_record_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    # Links to previous record in mission chain for integrity verification
    previous_record_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    chain_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # SHA-256

    # Agent identity
    agent_name: Mapped[str] = mapped_column(String(200), nullable=False)
    agent_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model_id: Mapped[str] = mapped_column(String(200), nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tier: Mapped[DecisionTier] = mapped_column(SAEnum(DecisionTier, native_enum=False), nullable=False)

    # ── The decision chain ──────────────────────────────────────────────────
    # What was the agent asked to do?
    intent: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # {
    #   "source": "user_message" | "workflow_step" | "delegation",
    #   "text": "...",          # the instruction, truncated to 4096 chars
    #   "task_id": "...",       # workflow task ID if applicable
    #   "delegated_by": "...",  # parent agent name if this is a sub-agent call
    # }

    # What did it reason? (chain-of-thought or structured plan)
    thinking: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # {
    #   "source": "extended_thinking" | "structured_steps" | "prompt_trace",
    #   "summary": "...",           # first 500 chars of reasoning
    #   "full_thinking_ref": "...", # Langfuse trace ID for full token stream
    #   "plan_formed": [...],       # structured steps if agent produced a plan
    #   "alternatives_considered": [...],  # if agent explicitly weighed options
    # }

    # What tools did it call?
    tool_invocations: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # [
    #   {
    #     "sequence": 1,
    #     "tool_name": "security.code.scan",
    #     "parameters": {...},          # sanitised — secrets redacted
    #     "result_summary": "...",      # first 500 chars of result
    #     "result_ref": "...",          # evidence path or Langfuse span ID
    #     "duration_ms": 1240,
    #     "success": true,
    #     "error": null,
    #   },
    #   ...
    # ]

    # What sub-agents did it delegate to?
    delegations: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # [
    #   {
    #     "agent_name": "security.webapp.triage.agent",
    #     "decision_record_id": "...",  # links to child AgentDecisionRecord
    #     "input_summary": "...",
    #     "output_summary": "...",
    #   }
    # ]

    # What did it decide? (full structured output, snapshotted at decision time)
    output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Full Pydantic model_dump() of the agent's output. For Tier 4 agents this
    # is mandatory — non-determinism means we cannot reconstruct this later.
    output_schema: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Python class name of the output Pydantic model e.g. "TriageOutput"
    output_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # SHA-256 of json.dumps(output, sort_keys=True) — detects post-hoc tampering

    # Did it match the intent?
    outcome: Mapped[DecisionOutcome] = mapped_column(
        SAEnum(DecisionOutcome, native_enum=False), nullable=False
    )
    outcome_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Human-readable explanation of why outcome != SUCCESS

    # What went wrong?
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    fallback_activated: Mapped[bool] = mapped_column(Boolean, default=False)
    fallback_description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Observability links
    langfuse_trace_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    langfuse_session_id: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Prompt reproducibility (enables auditor to reconstruct exact conditions)
    prompt_template_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tool_registry_snapshot_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_commit_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # Timing
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_adr_mission_sequence", "mission_id", "sequence_number"),
        Index("ix_adr_agent_name", "agent_name"),
        Index("ix_adr_outcome", "outcome"),
        Index("ix_adr_created_at", "created_at"),
    )
```

---

## Hash Chain Integrity

Each record's `chain_hash` is computed as:

```python
# modules/backend/services/agent_decision_service.py

import hashlib
import json

def compute_chain_hash(record: AgentDecisionRecord, previous_hash: str | None) -> str:
    """
    SHA-256 over the record's immutable content + previous chain hash.

    This links every record to all prior records. Modifying any record,
    inserting a gap, or deleting a record breaks the chain — detectable
    by a sequential hash verification pass.
    """
    payload = {
        "record_id": record.record_id,
        "mission_id": record.mission_id,
        "sequence_number": record.sequence_number,
        "agent_name": record.agent_name,
        "intent": record.intent,
        "output_sha256": record.output_sha256,
        "outcome": record.outcome,
        "started_at": record.started_at.isoformat(),
        "previous_hash": previous_hash or "GENESIS",
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode()
    ).hexdigest()


async def verify_chain(mission_id: str, session: AsyncSession) -> ChainVerificationResult:
    """
    Walk the chain for a mission. Returns the first broken link, if any.
    Used by the quarterly audit replay test and the integrity scan task.
    """
    records = await session.execute(
        select(AgentDecisionRecord)
        .where(AgentDecisionRecord.mission_id == mission_id)
        .order_by(AgentDecisionRecord.sequence_number)
    )
    previous_hash = None
    for record in records.scalars():
        expected = compute_chain_hash(record, previous_hash)
        if expected != record.chain_hash:
            return ChainVerificationResult(
                valid=False,
                broken_at_sequence=record.sequence_number,
                broken_record_id=record.record_id,
            )
        previous_hash = record.chain_hash
    return ChainVerificationResult(valid=True, record_count=count)
```

**Database enforcement:** The application role used by the platform (`mc_app`) has `INSERT` privilege on `agent_decision_records` only. `UPDATE` and `DELETE` are granted exclusively to a separate `mc_audit_admin` role used only for compliance operations. This is enforced at database level, not application level.

---

## Memory Provenance (6.5)

The MCD today is updated by patches from agent outputs with no record of which session or agent contributed each entry. This plan adds provenance to every MCD patch.

### MCD Patch Provenance Model

```python
# modules/backend/schemas/mcd.py  (extend existing)

class MCDPatchProvenance(BaseModel):
    """Provenance tag attached to every MCD patch."""
    session_id: str
    agent_name: str
    decision_record_id: str       # links to AgentDecisionRecord
    patched_at: datetime
    patch_hash: str               # SHA-256 of the patch content


class MCDPatch(BaseModel):
    """A single update to the Mission Context Document."""
    path: str                     # JSON path of the field being updated
    value: Any                    # new value
    provenance: MCDPatchProvenance
```

### Integrity Controls

**Pre-replay validation.** Before injecting MCD content into an agent's context window, the harness checks:
1. Every entry in the MCD has a valid `MCDPatchProvenance`
2. The provenance `decision_record_id` exists in `agent_decision_records`
3. The `patch_hash` matches the current content (detects post-hoc modification)

If any check fails, the affected entries are quarantined (excluded from context) and an `mcd.integrity_violation` audit event is emitted. The agent runs with the remaining valid entries.

**Selective revocation.** An entry can be revoked without clearing the full MCD:

```python
async def revoke_mcd_entry(
    mission_id: str,
    path: str,
    revoked_by: str,
    reason: str,
    session: AsyncSession,
) -> None:
    """Remove a single MCD entry by path. Appends a revocation record."""
    # MCD entry is nulled; revocation is recorded with actor and reason.
    # The AgentDecisionRecord for the original patch is annotated with
    # outcome=SUPERSEDED and outcome_notes = revocation reason.
```

**Memory integrity scan.** A scheduled task runs every 24 hours:
- Walks all active MCDs
- Verifies every entry has valid provenance
- Detects entries containing instruction-like patterns (heuristic: imperative verbs + second-person address in structured data fields)
- Emits `mcd.integrity_scan_completed` event with findings count

---

## Circuit Breaker Enhancements (6.6)

The four existing circuit breakers (budget, iteration cap, stall detection, duplicate detection — Plan 51 §4.6) remain unchanged. This plan adds the three gaps identified in the control objective review.

### Breaker 5: Error Rate

```python
# Error rate threshold: if the agent's error rate exceeds the threshold
# within a rolling time window, halt and escalate.

error_rate_window_seconds: int = 300        # 5-minute rolling window
error_rate_threshold: float = 0.5           # 50% of tool calls failing
error_rate_min_sample: int = 5              # don't trigger on < 5 calls
```

**Logic:** Count tool invocations in the last `error_rate_window_seconds`. If `failed / total >= threshold` and `total >= min_sample`, trigger `GateAction.ESCALATE` with `rule="error_rate_threshold"`. Evaluated at the same point as the other four breakers — before any LLM call, deterministically.

### Breaker 6: Single-Action Blast Radius

Per-action threshold for tools that affect external state. Expressed as a `BlastRadiusConstraint` on the tool registration:

```python
@agent.tool(
    name="security.injection.test_sqli",
    blast_radius=BlastRadiusConstraint(
        max_affected_rows=10,        # sqlmap: never extract more than 10 rows
        requires_gate_above=2,       # Stage 2+ requires human gate
        dry_run_first=True,          # produce dry-run estimate before executing
    )
)
async def test_sqli(ctx: RunContext[...], ...) -> ...:
    ...
```

Before executing any tool with a `BlastRadiusConstraint`, the harness:
1. Estimates the blast radius (rows affected, requests sent, data touched)
2. If estimate exceeds the constraint, halts and presents a gate review
3. If gate is `off` mode and constraint is exceeded, the tool call is blocked entirely — not escalated

This is harness-level enforcement. The agent cannot override it.

### Kill-Switch SLA and Activation Audit

**SLA:** A kill-switch activation (any scope: task, plan, all) must result in all affected agent processes halting within **30 seconds**. This is enforced via Temporal workflow cancellation — `workflow.cancel()` propagates to all running activities. The 30-second SLA is the activity heartbeat timeout.

**Auditability requirement:** Every kill-switch activation writes an `AgentDecisionRecord` with:
- `outcome = DecisionOutcome.ESCALATED`
- `error_code = "KILL_SWITCH_ACTIVATED"`
- `intent.source = "kill_switch"`
- `intent.text` = scope and actor (e.g. `"operator herman@icarus.com cancelled plan abc123"`)

This record is written by the harness, not by the agent. It appears in the hash chain for the mission.

**Review requirement:** Every `KILL_SWITCH_ACTIVATED` record triggers a `kill_switch.activated` platform event. The on-call runbook requires review within 24 hours. The review is recorded by annotating the `AgentDecisionRecord.outcome_notes` field with the reviewer's finding.

---

## Replay Test Procedure

This is the measurable outcome from control objective 6.4: "select a sample of consequential agent actions and reconstruct the complete chain from logs alone."

### Quarterly Replay Test

```python
# scripts/audit_replay_test.py

async def run_replay_test(mission_id: str, sample_size: int = 5) -> ReplayTestResult:
    """
    Reconstruct a sample of consequential agent decisions from the audit trail.

    Steps:
    1. Verify the hash chain for the mission is intact
    2. Select a random sample of Tier 3-4 records
    3. For each record, verify:
       a. intent is present and non-empty
       b. tool_invocations are present and reference valid evidence/trace IDs
       c. output is present and output_sha256 matches json.dumps(output)
       d. outcome is set
       e. langfuse_trace_id resolves to a real trace (if Langfuse available)
       f. prompt_template_hash matches current prompt file (if SAST, target_commit_sha resolves)
    4. Report: N records sampled, N reconstructed fully, N partially, N failed

    If any record cannot be fully reconstructed, the test fails.
    Failure means the logging control is broken — investigate before next run.
    """
```

**Frequency:** Quarterly, run by the security team against production audit records. Results stored as a compliance artifact in the mission workspace.

**Pass criteria:** 100% of sampled records fully reconstructed. Partial reconstruction (e.g. Langfuse trace expired) is flagged but does not fail the test if the structured fields are intact.

---

## Fallback Procedures

Control objective 6.6 requires documented, tested fallback procedures for when the agent system cannot execute. Three scenarios:

### Scenario A: Agent LLM provider unavailable

**Trigger:** `LLM_PROVIDER_FAILED` error after retries, or circuit breaker on provider error rate.

**Fallback:** Workflow step is marked `ESCALATED`. Platform emits `workflow.step.provider_unavailable` event. The on-call runbook specifies:
1. Check Copilot/Anthropic status page
2. If transient: retry the step manually via `POST /api/v1/missions/{id}/workflows/{wf}/steps/{step}/retry`
3. If extended outage: pause autonomous missions via emergency stop, notify mission owners

**Test:** Annually. Simulate provider failure by setting `SECURITY_ASSESSMENT_LLM_PROVIDER=offline` in a staging environment. Verify escalation fires, manual retry succeeds, emergency stop pauses correctly.

### Scenario B: OPA scope enforcement unavailable

**Trigger:** `OPA_UNAVAILABLE` after 3 retries (already in WASA error taxonomy with `retryable=True, retry_after_seconds=5`).

**Fallback:** Assessment halts entirely — cannot validate scope without OPA. Platform emits `roe.opa_unavailable` event. No fallback to permissive mode in production.

**Test:** Quarterly as part of circuit breaker test suite. Stop OPA container, assert WASA assessment halts, assert no tool calls proceed beyond the OPA check.

### Scenario C: Kill switch activated mid-assessment

**Trigger:** Operator activates kill switch.

**Fallback:** All running tool subprocesses are sent SIGTERM (30-second timeout, then SIGKILL). Evidence written so far is hashed and the integrity manifest is finalised. The assessment produces a partial `SecurityAssessmentReport` from phases completed before the halt. Partial report is clearly marked `assessment_status: HALTED` with `halt_reason` and `halt_at` fields.

**Test:** Annually. Activate kill switch mid-assessment in staging. Verify subprocess cleanup, partial report generation, and `KILL_SWITCH_ACTIVATED` audit record.

---

## Platform Reuse Map

| Capability | Existing code | What this plan adds |
|---|---|---|
| Decision audit rows | `execution_decisions` table (supervisor decisions only) | `agent_decision_records` table covering all Tier 3-4 agents; extends the existing audit pattern |
| Hash integrity | `evidence.py` SHA-256 on WASA artefacts | Hash chain across `agent_decision_records` rows; same `hashlib.sha256` pattern |
| Circuit breakers | Plan 51 §4.6 — 4 breakers, deterministic, pre-LLM | Breaker 5 (error rate), Breaker 6 (blast radius); same `GateAction.ESCALATE` output |
| Kill switch | Ref arch 40 `POST /api/v1/agent/cancel`; plan 46 emergency stop | SLA (30s), audit record, review requirement |
| MCD | Existing MCD with unprovenanced patches | `MCDPatchProvenance` on every patch; pre-replay validation; selective revocation |
| Langfuse | WASA §1.1 — EU AI Act Art. 12 logging | `langfuse_trace_id` reference field on every decision record — links structured record to full token stream |

---

## Anti-patterns

- **Do not write `AgentDecisionRecord` from within agent code.** The agent cannot be trusted to accurately self-report. The harness writes the record after the agent run completes, from the structured `RunResult` object.
- **Do not compress or abbreviate `output` for Tier 4 records.** Non-determinism means the output cannot be reconstructed later. Store the full `model_dump()` at decision time.
- **Do not grant the application database user UPDATE or DELETE on `agent_decision_records`.** This is the only control that makes the audit tamper-resistant. A misconfigured migration that grants these permissions breaks the control.
- **Do not skip the hash chain for "low-importance" Tier 3 decisions.** The chain is only as strong as its completeness. Gaps in the sequence number are detectable and reportable.
- **Do not store raw credentials, secret values, or PII in `tool_invocations.parameters`.** Apply the same redaction rules as WASA `redact_output: true` — secrets are replaced with `<<REDACTED>>` before the field is written.
- **Do not treat Langfuse as the primary audit record.** Langfuse is the observability tool; `agent_decision_records` is the audit record. Langfuse may be unavailable, may rotate traces on a short retention window, or may not be deployed in all environments. The structured record must be self-contained.

---

## Tests

| Test | Type | What to assert |
|---|---|---|
| Hash chain integrity | Unit | Modifying any field of a record breaks the chain at that sequence number |
| Insert-only enforcement | Integration | `UPDATE agent_decision_records` raises permission error for `mc_app` role |
| Tier 4 output snapshot | Integration | Tier 4 agent run produces a record with non-null `output` and matching `output_sha256` |
| Tool invocation capture | Integration | Every tool call within a run appears in `tool_invocations` with correct `success` and `result_summary` |
| MCD provenance on patch | Unit | Every MCD update produces a patch with valid `MCDPatchProvenance` |
| MCD pre-replay validation | Unit | A patched MCD entry with mismatched `patch_hash` is quarantined, not injected into context |
| MCD selective revocation | Integration | Revoking a path nulls the entry; linked `AgentDecisionRecord` is annotated with `SUPERSEDED` |
| Breaker 5 error rate | Unit | 3 of 5 tool calls failing within the window triggers `GateAction.ESCALATE, rule="error_rate_threshold"` |
| Breaker 6 blast radius | Unit | Tool call with estimated blast radius above constraint halts before execution |
| Kill switch 30s SLA | Integration (staging) | Kill switch activation stops all running activities within 30 seconds |
| Kill switch audit record | Integration | Kill switch activation writes an `AgentDecisionRecord` with `KILL_SWITCH_ACTIVATED` error code |
| Quarterly replay test | Script | `audit_replay_test.py` against a known-good mission produces 100% reconstruction rate |
| MCD integrity scan | Unit | An MCD entry containing `"Ignore previous instructions"` is flagged by the integrity scan |

---

## Implementation Phases

### Phase 1 — Structured decision records (foundation)

**Scope:** Database table, hash chain, harness integration for supervisor decisions and WASA Tier 3-4 agents.

Build:
- `AgentDecisionRecord` model and migration
- `AgentDecisionService` with `write_record()` and `verify_chain()`
- Database role enforcement (`mc_app` INSERT-only)
- Harness integration: wrap `run_agent()` in the agent executor to write a record after every Tier 3-4 run
- `audit_replay_test.py` script
- Tests: hash chain, insert-only, output snapshot, tool invocation capture

**Does not include:** MCD provenance, new circuit breakers, kill-switch SLA.

### Phase 2 — MCD provenance and memory integrity

**Scope:** Provenance on MCD patches, pre-replay validation, selective revocation, integrity scan task.

Build:
- `MCDPatchProvenance` model and patch schema extension
- Pre-replay validation in the MCD injection path
- `revoke_mcd_entry()` function
- Scheduled integrity scan (24-hour interval)
- Tests: provenance on patch, pre-replay validation, selective revocation, integrity scan

### Phase 3 — Circuit breaker enhancements and kill-switch SLA

**Scope:** Breakers 5 and 6, kill-switch SLA enforcement, activation audit, fallback procedures.

Build:
- Breaker 5: error rate threshold in `AutonomousPostRunReviewer`
- Breaker 6: `BlastRadiusConstraint` on tool registrations; harness pre-execution check
- Kill-switch SLA: 30s heartbeat timeout configuration; audit record on activation
- Fallback procedure runbooks for Scenarios A, B, C
- Tests: all three new circuit breakers, kill-switch SLA, fallback procedure tests (staging)

---

## Compliance Mapping

| Framework | Requirement | How this plan addresses it |
|---|---|---|
| EU AI Act Art. 12 | Documentation of AI system decisions | `AgentDecisionRecord` is the Art. 12 log for consequential decisions; Langfuse link for full token stream |
| BCBS 239 | Accuracy and integrity of risk data for regulated decisions | Hash chain prevents post-hoc modification; insert-only DB role; `output_sha256` detects tampering |
| DORA Art. 10 (ICT risk) | Audit trail for automated decision-making | Structured record with intent/reasoning/output/outcome; quarterly replay test |
| SARB Directive 01/2024 | 24-hour material incident reporting | Kill switch activation triggers `kill_switch.activated` event; review requirement within 24 hours |
| APRA CPS 234 | Systematic control testing | Circuit breakers tested quarterly; fallback procedures tested annually |
