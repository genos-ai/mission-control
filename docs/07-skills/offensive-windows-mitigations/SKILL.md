# SKILL: Week 6: Understanding Windows Mitigations

## Metadata
- **Skill Name**: windows-mitigations
- **Folder**: offensive-windows-mitigations
- **Source**: https://github.com/SnailSploit/offensive-checklist/blob/main/6-windows-mitigations.md

## Description
Deep-dive on Windows exploit mitigations: ASLR, DEP/NX, CFG, CET/Shadow Stack, SEHOP, Heap Guard, ACG, Arbitrary Code Guard. Covers both the protection mechanism and known bypass techniques. Use when researching Windows exploit mitigations, planning bypass strategies, or understanding protection depth.

## Trigger Phrases
Use this skill when the conversation involves any of:
`Windows mitigations, ASLR, DEP, NX, CFG, CET, shadow stack, SEHOP, heap guard, ACG, mitigation bypass, exploit mitigation, Windows hardening`

## Instructions for Claude

When this skill is active:
1. Fetch the methodology from the **Source** URL above, then apply it as the operational checklist
2. Follow steps in order unless the user specifies otherwise
3. For each technique, consider applicability to the current target/context
4. Track which checklist items have been completed
5. Suggest next steps based on findings

---

## Full Methodology

Not vendored in this repository. Retrieve it from the **Source** URL above.

The upstream file is approximately 530 KB (roughly 133,000 tokens). It exceeds
this repository's 500 KB file ceiling (`check-added-large-files`, see
`.pre-commit-config.yaml`) and is too large to load as a single skill, so only
the metadata above is held here.
