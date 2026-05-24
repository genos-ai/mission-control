#!/usr/bin/env python3
"""
Anonymise baseline-vs-v2 deliverables for blind comparison.

For each question, takes the baseline (.md) and v2 (.md) deliverables,
randomly assigns A/B labels, writes anonymised copies, and writes a
key file (kept separate so the reader can't peek before scoring).

Usage:
  # Anonymise all 3 questions:
  python scripts/think_tank_anonymise.py

  # Reveal the mapping after scoring:
  python scripts/think_tank_anonymise.py --reveal
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import click

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

VALIDATION_DIR = PROJECT_ROOT / "var" / "validation"
BASELINE_DIR = VALIDATION_DIR / "baseline"
V2_DIR = VALIDATION_DIR / "v2"
BLIND_DIR = VALIDATION_DIR / "blind"
KEY_FILE = VALIDATION_DIR / ".blind_key.json"

QUESTIONS = {
    "q1": "What will agentic AI do to UK knowledge-work employment by 2030?",
    "q2": "Will the EU AI Act be substantially weakened by enforcement gaps and sectoral carve-outs by end-2027?",
    "q3": "Will commercial nuclear fusion deliver utility-grade electricity at competitive cost before 2040?",
}


def _anonymise_one(q_id: str, q_text: str, seed: int) -> dict:
    """Anonymise one question's pair. Returns the A/B → source mapping."""
    baseline_md = BASELINE_DIR / f"{q_id}_solo.md"
    v2_md = V2_DIR / f"{q_id}.md"

    missing = [p for p in (baseline_md, v2_md) if not p.exists()]
    if missing:
        raise FileNotFoundError(
            f"Missing input(s) for {q_id}: {[str(p) for p in missing]}",
        )

    rng = random.Random(seed)
    labels = ["A", "B"]
    rng.shuffle(labels)
    mapping = {labels[0]: "baseline", labels[1]: "v2"}

    BLIND_DIR.mkdir(parents=True, exist_ok=True)
    for label, source in mapping.items():
        src = baseline_md if source == "baseline" else v2_md
        dst = BLIND_DIR / f"{q_id}_{label}.md"
        # Strip any obvious source markers from the markdown.
        body = src.read_text()
        for marker in (
            "baseline", "BASELINE", "Baseline",
            "v2", "V2",
            "Plan 79", "Think Tank v2",
            "single-call", "deliberation_loop",
        ):
            body = body.replace(marker, "")
        # Add a neutral header.
        dst.write_text(
            f"# Deliverable for question {q_id.upper()}\n"
            f"# {q_text}\n\n"
            f"---\n\n{body}",
        )
        print(f"  {dst.relative_to(PROJECT_ROOT)}  <-  {src.relative_to(PROJECT_ROOT)}")

    return mapping


@click.command()
@click.option(
    "--reveal", is_flag=True,
    help="Print the A/B → source mapping (after scoring).",
)
@click.option(
    "--seed", default=None, type=int,
    help="RNG seed for the shuffle (default: random). Use a fixed value to "
         "make anonymisation reproducible.",
)
def main(reveal: bool, seed: int | None) -> None:
    if reveal:
        if not KEY_FILE.exists():
            print(f"No key file at {KEY_FILE}. Run anonymise first.")
            sys.exit(1)
        key = json.loads(KEY_FILE.read_text())
        print("\n=== Blind key (do not peek before scoring) ===\n")
        for q_id, mapping in key.items():
            print(f"{q_id}:")
            for label, source in sorted(mapping.items()):
                print(f"  {label} -> {source}")
        return

    # Anonymise mode
    overall_seed = seed if seed is not None else random.randint(0, 2**31 - 1)
    rng = random.Random(overall_seed)
    key: dict[str, dict[str, str]] = {}
    print(f"Anonymising (seed={overall_seed}):\n")
    for q_id, q_text in QUESTIONS.items():
        try:
            mapping = _anonymise_one(q_id, q_text, rng.randint(0, 2**31 - 1))
            key[q_id] = mapping
        except FileNotFoundError as e:
            print(f"  {q_id}: SKIPPED ({e})")
            continue
        print()

    KEY_FILE.write_text(json.dumps(key, indent=2))
    print(f"\nKey saved to {KEY_FILE.relative_to(PROJECT_ROOT)} (do not open until scoring is done).")
    print(f"\nBlind deliverables: {BLIND_DIR.relative_to(PROJECT_ROOT)}/")
    print(f"  Read in pairs (e.g. q1_A.md and q1_B.md) and score each.")
    print(f"  Then run: python scripts/think_tank_anonymise.py --reveal\n")


if __name__ == "__main__":
    main()
