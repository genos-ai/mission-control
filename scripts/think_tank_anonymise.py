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
KEY_FILE = VALIDATION_DIR / ".blind_key.json"

# Each comparator family lives in its own directory under var/validation/
# and uses its own per-question file-naming convention. baseline is the
# fixed reference; --comparator selects the challenger family to A/B
# against it.
COMPARATOR_LAYOUTS = {
    "v2": {
        "dir": VALIDATION_DIR / "v2",
        "filename": lambda q_id: f"{q_id}.md",
    },
    "v1_decomposed": {
        "dir": VALIDATION_DIR / "v1_decomposed",
        "filename": lambda q_id: f"{q_id}_v1d.md",
    },
}

QUESTIONS = {
    "q1": "What will agentic AI do to UK knowledge-work employment by 2030?",
    "q2": "Will the EU AI Act be substantially weakened by enforcement gaps and sectoral carve-outs by end-2027?",  # noqa: E501
    "q3": "Will commercial nuclear fusion deliver utility-grade electricity at competitive cost before 2040?",  # noqa: E501
}


def _anonymise_one(
    q_id: str,
    q_text: str,
    seed: int,
    comparator: str,
    blind_dir: Path,
) -> dict:
    """Anonymise one question's pair. Returns the A/B → source mapping."""
    layout = COMPARATOR_LAYOUTS[comparator]
    baseline_md = BASELINE_DIR / f"{q_id}_solo.md"
    challenger_md = layout["dir"] / layout["filename"](q_id)

    missing = [p for p in (baseline_md, challenger_md) if not p.exists()]
    if missing:
        raise FileNotFoundError(
            f"Missing input(s) for {q_id}: {[str(p) for p in missing]}",
        )

    rng = random.Random(seed)
    labels = ["A", "B"]
    rng.shuffle(labels)
    mapping = {labels[0]: "baseline", labels[1]: comparator}

    blind_dir.mkdir(parents=True, exist_ok=True)
    for label, source in mapping.items():
        src = baseline_md if source == "baseline" else challenger_md
        dst = blind_dir / f"{q_id}_{label}.md"
        # Strip any obvious source markers from the markdown.
        body = src.read_text()
        for marker in (
            "baseline",
            "BASELINE",
            "Baseline",
            "v2",
            "V2",
            "v1_decomposed",
            "v1-decomposed",
            "v1d",
            "Plan 79",
            "Plan 81",
            "Think Tank v2",
            "single-call",
            "deliberation_loop",
        ):
            body = body.replace(marker, "")
        # Add a neutral header.
        dst.write_text(
            f"# Deliverable for question {q_id.upper()}\n" f"# {q_text}\n\n" f"---\n\n{body}",
        )
        print(f"  {dst.relative_to(PROJECT_ROOT)}  <-  {src.relative_to(PROJECT_ROOT)}")

    return mapping


@click.command()
@click.option(
    "--reveal",
    is_flag=True,
    help="Print the A/B → source mapping (after scoring).",
)
@click.option(
    "--comparator",
    default="v2",
    type=click.Choice(sorted(COMPARATOR_LAYOUTS.keys())),
    help="Which challenger family to A/B against baseline. v2 is the "
    "original Plan 79 v2; v1_decomposed is Plan 81 (Phase 0 "
    "decomposed). The blind/key files live in "
    "var/validation/blind_{comparator}/ so multiple comparators "
    "do not collide.",
)
@click.option(
    "--seed",
    default=None,
    type=int,
    help="RNG seed for the shuffle (default: random). Use a fixed value to "
    "make anonymisation reproducible.",
)
def main(reveal: bool, comparator: str, seed: int | None) -> None:
    blind_dir = VALIDATION_DIR / f"blind_{comparator}"
    key_file = VALIDATION_DIR / f".blind_key_{comparator}.json"

    if reveal:
        if not key_file.exists():
            print(f"No key file at {key_file}. Run anonymise first.")
            sys.exit(1)
        key = json.loads(key_file.read_text())
        print(f"\n=== Blind key for {comparator} (do not peek before scoring) ===\n")
        for q_id, mapping in key.items():
            print(f"{q_id}:")
            for label, source in sorted(mapping.items()):
                print(f"  {label} -> {source}")
        return

    # Anonymise mode
    overall_seed = seed if seed is not None else random.randint(0, 2**31 - 1)
    rng = random.Random(overall_seed)
    key: dict[str, dict[str, str]] = {}
    print(f"Anonymising baseline vs {comparator} (seed={overall_seed}):\n")
    for q_id, q_text in QUESTIONS.items():
        try:
            mapping = _anonymise_one(
                q_id,
                q_text,
                rng.randint(0, 2**31 - 1),
                comparator,
                blind_dir,
            )
            key[q_id] = mapping
        except FileNotFoundError as e:
            print(f"  {q_id}: SKIPPED ({e})")
            continue
        print()

    key_file.write_text(json.dumps(key, indent=2))
    print(
        f"\nKey saved to {key_file.relative_to(PROJECT_ROOT)} (do not open until scoring is done)."
    )
    print(f"\nBlind deliverables: {blind_dir.relative_to(PROJECT_ROOT)}/")
    print("  Read in pairs (e.g. q1_A.md and q1_B.md) and score each.")
    print(
        f"  Then run: python scripts/think_tank_anonymise.py --comparator {comparator} --reveal\n"
    )


if __name__ == "__main__":
    main()
