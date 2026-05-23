# Think Tank: A Multi-Agent Deliberation System for Contested Questions

## 1. Executive summary

The Think Tank system is buildable in PydanticAI on Claude models and earns its token cost on the narrow class of questions it is designed for: contested, multi-lens, open questions where the failure mode of a single model pass is not factual error but premature convergence on the mainstream prior. On the empirical evidence, naive multi-agent debate gives material but modest gains on closed-answer reasoning benchmarks (Du et al. report a single-agent to three-agent two-round lift from 67.0% to 81.8% on arithmetic and 63.9% to 71.1% on MMLU using GPT-3.5), and a disciplined variant beats single-pass reasoning on harder discriminative tasks (Khan et al., ICML 2024 Best Paper: 76% non-expert judge accuracy with debate vs 48% naive on QuALITY). Recent critiques (Smit et al. ICML 2024; Estornell and Liu, NeurIPS 2024; "Talk Isn't Always Cheap", arXiv:2509.05396, 2025) show that the default debate setup is brittle: accuracy can decline over rounds, agents copy each other's answers under social pressure, and the system collapses to the majority prior. Three deliberate counter-measures must be designed in from the start.

The build target is a seven-agent system: one researcher, four reasoning-diverse debaters, one dedicated adversarial critic, and one synthesiser. The orchestration runs blind opening positions (debaters commit before seeing each other), three structured debate rounds (default; max five) with the critic invoked every round against the weakest assumption of every debater, and early stopping when stance vectors stabilise across two consecutive rounds. The synthesiser is forbidden from voting; it produces a structured deliverable that preserves live disagreements, names dissenters by reasoning method, and identifies the cruxes on which reasonable observers part company.

Recommended defaults: Claude Sonnet 4.6 for the debaters and critic, Claude Opus 4.7 for the synthesiser, Claude Haiku 4.5 for the researcher. Estimated cost of one full run at defaults is approximately US$1.05 to $1.20, with end-to-end latency of 90 to 180 seconds. The three highest-probability failure modes are sycophancy cascade in late rounds, collapse to the mainstream prior despite the persona prompts, and synthesiser flattening; each has a specific mitigation baked into the design below.

## 2. Research findings

### 2.1 Does structured debate beat single-pass reasoning?

Mixed. The evidence supports a narrower claim: structured debate beats naive single-pass on tasks that require reasoning under disagreement, but loses to a well-tuned single agent (chain-of-thought plus self-consistency) on most closed-answer benchmarks.

- **Du et al., ICML 2024 (arXiv:2305.14325).** With three agents and two rounds of debate on GPT-3.5, arithmetic accuracy rose from 67.0 ± 4.7% to 81.8 ± 2.3% (+14.8 points), MMLU from 63.9% to 71.1% (+7.2), chess move validity from 29.3% to 45.2% (+15.9), and biographies factuality from 66.0% to 73.8%. They explicitly note that "stubborn" debater prompts produce longer, better debates: the prompt phrasing "Using the opinion of other agents as additional advice, can you give an updated response" outperforms "Based off the opinion of other agents, can you give an updated response" on GSM8K (approximately 85% vs 80% per their Figure 12). They observe directly: "we found that prompts that encouraged models to be more 'stubborn' based on their own solutions led to longer debates and better final solutions."
- **Liang et al., EMNLP 2024 (arXiv:2305.19118).** Their MAD framework with affirmative/negative debaters and a judge lifted GPT-3.5 on Counter-Intuitive Arithmetic Reasoning from 26.0% (baseline) and 27.5% (self-reflect) to 37.0% (MAD), closing two thirds of the gap to GPT-4 at 51.0%. They identified the **Degeneration of Thought (DoT)** problem: once a model commits, self-reflection cannot dislodge it. Multi-agent debate addresses DoT only if disagreement is actively maintained. Their tit-for-tat intensity Level 2 ("It's not necessary to fully agree with each other's perspectives, as our objective is to find the correct answer") outperformed Level 3 ("must disagree on every point"), which produced measured disagreement of 0.988 but worse final performance: forced disagreement degrades into theatre.
- **Khan et al., ICML 2024 Best Paper (arXiv:2402.06782).** Two-debater protocol on QuALITY reading comprehension: non-expert judges reached 76% accuracy (88% for humans) versus 48% (60%) for naive baselines. Optimising debaters for persuasiveness improved truth identification, contradicting the worry that more persuasive debaters mislead more.
- **Smit et al., ICML 2024 (arXiv:2311.17371).** Benchmarked MAD vs self-consistency vs ensembling. Headline finding: "multi-agent debating systems, in their current form, do not reliably outperform other proposed prompting strategies, such as self-consistency and ensembling using multiple reasoning paths." Their novel intervention was the prompt line "you should agree with the other agents X% of the time", treated as a hyperparameter. With that knob tuned, Multi-Persona gained approximately 15% on USMLE and Society of Mind approximately 5%; optimum was approximately 90% agreement on medical QA and inverted (low agreement) on Counter-Intuitive Arithmetic Reasoning. MAD is hyperparameter-sensitive, not inherently superior.
- **Estornell and Liu, NeurIPS 2024.** Echo chamber effect dominates: "as the number of similar agents increases, the debate procedure is more greatly impacted by the echo chamber effect, i.e., the probability that a round of debate results in a change to the most likely concept, perceived by agents, approaches 0." Proposed interventions: information-diversity injection per round, quality-pruning, misconception-refutation.
- **"Talk Isn't Always Cheap" (arXiv:2509.05396, 2025).** Debate can decrease accuracy over rounds. Correct-to-incorrect transitions exceed incorrect-to-correct ones in rounds 2+ under social pressure. Sycophancy is the dominant cause; "the proportion of correct-to-incorrect transitions exceeds the proportion of incorrect-to-correct ones in subsequent rounds."
- **"Peacemaker or Troublemaker" (arXiv:2509.23055, 2025).** Recommends capping debate at 2-3 substantive exchanges because "sycophancy intensifies in later rounds."
- **"Stay Focused: Problem Drift in Multi-Agent Debate" (arXiv:2502.19559).** Seven-turn debates dropped voting accuracy by 4.65% on average; the DRIFTJudge intervention regained most of the loss.

**Diminishing returns, point estimates from Du et al.:** Arithmetic at 1/3/5/7 agents = 72/87/90/91%; MMLU at 1/3/5/7 = 64/76/78/78.5%. The fifth agent buys roughly 2-3 accuracy points; the seventh roughly 0.5. The same logarithmic shape holds for rounds: most of the lift arrives by round two, plateau by round three, decay risk from round four onwards under sycophantic conditions.

### 2.2 Existing frameworks and patterns

- **AutoGen (Microsoft).** GroupChat with a manager that selects the next speaker; SocietyOfMindAgent wraps an inner group chat and applies a `response_preparer` to extract the final answer. Strength: clean wrapping of multi-turn deliberation as a single callable. Weakness: round-robin or LLM-routed turn-taking does not guard against convergence.
- **LangGraph supervisor pattern.** A dedicated routing node uses structured output to pick which specialist runs next. Strength: explicit, traceable routing. Weakness: supervisor cost compounds; the network topology (any-agent-to-any) tends to chaos.
- **CrewAI.** Role-based agents (role, goal, backstory) executing sequential or hierarchical processes. Strength: clear team mental model. Weakness: roles are job titles ("Data Scientist", "Researcher"), which the persona research below suggests changes style more than reasoning. Comparative benchmarks: JetThoughts (2025) reports CrewAI executes 5.76× faster than LangGraph on certain QA tasks; Pooya Golchian (Pooya.blog, 2026) benchmarked the same frameworks on Qwen3 32B via Ollama for complex multi-step tasks (8+ steps with planning and backtracking) and found "LangGraph completed 62% of complex multi-step tasks vs CrewAI's 54%", with AutoGen at 58%.
- **DeepMind / Irving et al., "AI safety via debate" (2018).** Two-debater zero-sum game with a human judge. Theoretically, optimal play covers PSPACE. Practical descendants (Khan et al. 2024) show the protocol works on real tasks; the modern systems use it as a discriminative oracle, not a generative deliberation.
- **Minsky "Society of Mind".** The inspiration for AutoGen's SocietyOfMindAgent and the Du et al. framing. Useful as a metaphor; not directly buildable.

### 2.3 Persona design for genuine cognitive diversity

Persona prompting changes style much more than it changes reasoning. Hu and Collier (ACL 2024, arXiv:2402.10811) report that "persona variables can explain <10% variance in annotations in existing subjective NLP datasets" and add: "Most subjective NLP datasets fall into this category, casting doubt on simulating diverse perspectives." Kambhatla, Shaib and Govindarajan (arXiv:2505.17390; Findings of EMNLP 2025) report: "while persona-prompting does improve lexical diversity (especially with larger models), fine-grained detail in personas doesn't increase diversity noticeably." Savir et al. (Wharton/Penn "Prompting Science Report 4: Playing Pretend", arXiv:2512.05858, 2024) tested expert personas on six models against GPQA Diamond and MMLU-Pro and conclude: "In-Domain Experts: Assigning the model an expert persona matched to the problem type had no significant impact on performance." Worse, "Bias Runs Deep" (Gupta et al., ICLR 2024) shows persona assignment can degrade reasoning by surfacing implicit stereotypes.

Implication for this design: differentiate agents by **reasoning method** (how they decompose a problem) and **value frame** (what they optimise for), not by occupational persona. This matches the settled design principle in the brief.

### 2.4 Anti-convergence prompt techniques (the most important research output)

Concrete, tested techniques, each tied to a paper and a verbatim prompt where one exists:

1. **Stubborn prompt phrasing (Du et al., Figure 12).** Replace "Based off the opinion of other agents, can you give an updated response" with "Using the opinion of other agents **as additional advice**, can you give an updated response". Same information, different prior on convergence. Empirically lengthens debate and improves final accuracy on GSM8K.
2. **Tit-for-tat intensity instruction (Liang et al., Appendix D Table 11).** Insert one of four explicit consensus instructions into the meta-prompt. Their optimal setting was Level 2 verbatim: "It's not necessary to fully agree with each other's perspectives, as our objective is to find the correct answer." Level 3 ("Both sides must disagree with each other on every point of the debate. There should be no consensus whatsoever") produced highest measured disagreement (0.988) but worse performance.
3. **Agreement-intensity hyperparameter (Smit et al.).** Inject the prompt line "you should agree with the other agents X% of the time" where X is tuned. Their optimal on USMLE was approximately 90% (high agreement) for medical QA; for Counter-Intuitive AR the optimum was inverted (low agreement). For **contested open questions** the value should sit low (15-30%), because the cost of premature consensus exceeds the cost of held disagreement.
4. **Devil's advocate role (Smit et al. Multi-Persona, Liang et al. negative side).** A dedicated agent whose system prompt opens with the explicit instruction to disagree (Smit et al. Appendix A.6: "You disagree with my answer. Provide your answer and reasons, and a capital letter answer at the end of your response"). This survives as a position-holding device when paired with the agreement-intensity knob.
5. **Confidence-based persistence rule.** Phrased instruction such as "Concede only when the counter-argument identifies a specific factual error or a load-bearing logical gap in your reasoning. Do not concede because the other agent sounds confident or articulate." Anchored in Sharma et al. 2023 and the explicit recommendations in arXiv:2509.23055.
6. **Misconception refutation and quality pruning (Estornell and Liu, NeurIPS 2024).** Before each round, drop any agent message that is a paraphrase of the round-before majority, and add an explicit "name the misconception you believe the other agents are operating under" turn. Empirically reduces echo chamber.
7. **Hold-versus-concede schema.** Force each debater to emit a discrete decision per round (`HOLD`, `REFINE`, `CONCEDE_PARTIAL`, `CONCEDE_FULL`) with a written justification. Makes sycophancy mechanically visible.
8. **Cap on rounds.** 2-3 substantive exchanges, per the "Peacemaker or Troublemaker" finding that sycophancy intensifies in later rounds.

### 2.5 Synthesis techniques

LLM-as-Judge naive aggregation underperforms in adversarial settings. AgentAuditor (arXiv:2602.09341) shows that reasoning-tree path search beats majority vote by up to 5 points and LLM-as-Judge by up to 3 on five MAS settings, and that **majority vote is brittle when the correct answer is the minority view**. The PROClaim courtroom-style framework (arXiv:2603.28488) reaches 81.7% on Check-COVID, 10 points above standard MAD, by using a structured deliberation with heterogeneous multi-judge aggregation.

Implication: the synthesiser should not vote. It should map the disagreement, name the cruxes that produce the disagreement, present the strongest version of each surviving position (steelman), and only then commit to a recommendation, with explicit uncertainty owned.

### 2.6 Known failure modes and detection

| Failure mode | Detection signal | Mitigation built into design |
|---|---|---|
| Sycophancy cascade | Agents revising correct answers to match peers; drop in stance-vector variance round-on-round | HOLD/CONCEDE schema; critic invoked every round; confidence-persistence rule in system prompt |
| Mode collapse / mainstream prior | All four debaters reach the conventional take by round two | Blind opening; agreement-intensity at 20%; mandatory maverick framing in two debater prompts |
| Circular argument | Same arguments repeated under different phrasing | Quality-pruning step; round-summary by critic identifying repetition |
| Coherence decay over long round counts | Accuracy drops measured by Stay Focused paper from round 4 onward (-4.65% by round 7) | Default 3 rounds; max 5; early-stop on stance stability |
| Token cost blowout | n_agents × n_rounds × context growth | Sparse topology (each debater sees own previous turn plus opponents' last turn only, not full history); Sonnet 4.6 default |
| Echo chamber from correlated priors | Agents share an unstated assumption | Critic's whole job; one debater (Adversarial Empiricist) explicitly required to challenge consensus |

### 2.7 PydanticAI and Claude integration

- **Multi-agent patterns (ai.pydantic.dev/multi-agent-applications).** Three native patterns: single-agent workflows; agent delegation via `@agent.tool` (a parent agent's tool calls a delegate agent's `.run`); programmatic hand-off where application code invokes agents in sequence. The third matches the Think Tank requirement: the orchestrator (Mission Control) runs each agent in turn, passing prior outputs as input.
- **Structured outputs.** Each PydanticAI `Agent` is parameterised by `output_type=SomePydanticModel`. The framework converts the Pydantic schema into a tool call and validates the response. Anthropic added native Structured Outputs in public beta (November 2025, Sonnet 4.5 / Opus 4.1+) guaranteeing JSON schema compliance.
- **Implication.** Every debater turn returns a structured object (position statement, confidence, hold/concede decision, named cruxes). The synthesiser consumes structured records, not free text, which is what makes preserving disagreement mechanically achievable.

### 2.8 Anthropic Claude pricing (April-May 2026)

| Model | Input ($/MTok) | Output ($/MTok) |
|---|---|---|
| Claude Opus 4.7 | 5.00 | 25.00 |
| Claude Sonnet 4.6 | 3.00 | 15.00 |
| Claude Haiku 4.5 | 1.00 | 5.00 |

Prompt caching reduces cached input by up to 90%; Batch API discounts everything 50%.

## 3. Agent roster

Seven agents. Four debaters, one researcher, one critic, one synthesiser. The debaters are constructed on two orthogonal axes per the brief: **reasoning method** (how) and **value frame** (what to optimise). The four chosen pairs are deliberately non-overlapping.

| Agent | Reasoning method | Value frame | Characteristic move | Known blind spot |
|---|---|---|---|---|
| Researcher | Empirical aggregation | Truth, recency | Pulls named numbers, dates, conflicting estimates; surfaces base rates | Selection bias toward consensus sources |
| Debater A: Systems Mapper | Systems thinking, feedback loops, second-order effects | Resilience under shock | "What does this look like at year five if the obvious first-order effect is correct?" | Underweights local agency; can drift to abstract systems narratives |
| Debater B: Reductionist Quant | Reductionist, base-rate, mechanism-grounded | Efficiency, measurable outcomes | "What is the specific quantitative claim and what would falsify it?" | Discounts what cannot be measured cleanly; can miss qualitative regime shifts |
| Debater C: Adversarial Empiricist | Falsificationist, historical-analogy | Truth via prediction track record | "Name the prior moment this resembles and what actually happened" | Anchors on historical priors that may not apply to genuinely novel regimes |
| Debater D: Distributional Ethicist | Pluralist, equity-weighted, power-aware | Equity, who bears the cost | "Who wins, who loses, and which voices are absent from the data?" | Can over-index on distributional concerns and miss aggregate effects |
| Critic | Adversarial; holds no position | Truth via attacking weakest link | "The load-bearing assumption in agent X's argument is Y, which fails if Z." | None it is allowed to have; the critic is not a debater |
| Synthesiser | Structured cartographer | Decision-usefulness without flattening | Maps positions, names cruxes, presents steelmen, owns uncertainty | Risk of false balance; mitigated by required minority preservation |

**Justification for this roster.** The four debaters cover the four quadrants of (mechanism vs system) × (efficiency vs equity), which is the minimum diversity needed to break correlated priors on a contested question. A Systems Mapper and a Reductionist Quant produce genuinely incompatible answer formats (qualitative second-order narrative vs falsifiable quantitative claim) and so cannot trivially converge. The Adversarial Empiricist is the maverick seat: explicitly required to challenge mainstream consensus by citing historical priors. The Distributional Ethicist counter-weights the technocratic frame the other three share.

**Default size: four debaters plus critic plus synthesiser plus researcher = seven.** Du et al.'s curves show the fifth agent buys 2-3 accuracy points on closed tasks and almost nothing thereafter. For contested open questions, the marginal cost of a fifth or sixth debater is high (token cost approximately +20-25% per debater) and the marginal diversity is low because the four quadrants are already covered. A fifth or sixth debater earns its keep only when the question crosses into a genuinely new domain (e.g. an explicit geopolitical or theological dimension that none of the four frames captures). Maximum: six debaters.

## 4. System prompts

Domain-neutral. UK English. Copy-paste ready. Variables `{{QUESTION}}`, `{{RESEARCH_PACKET}}`, `{{ROUND_INDEX}}`, `{{ALL_OPENING_POSITIONS}}`, `{{OPPONENT_POSITIONS_LAST_ROUND}}`, `{{OWN_PREVIOUS_POSITION}}`, `{{CRITIC_ATTACK_ON_YOU}}`, `{{ALL_POSITIONS_THIS_ROUND}}`, `{{FULL_TRANSCRIPT}}`, `{{ALL_CRITIC_REPORTS}}`, `{{FINAL_POSITIONS}}` are interpolated by Mission Control.

### 4.1 Researcher

```
You are the Researcher for a structured deliberation on a contested, open question.

Your job is to assemble an evidence packet that the debating agents will use. You are not a debater. You do not take a position. You do not summarise into a single answer.

Question: {{QUESTION}}

Produce a research packet with the following sections, in this order:

1. WHAT IS ACTUALLY KNOWN. Named, dated, sourced claims. Prefer primary sources, peer-reviewed work, or named institutional forecasts. Mark each claim with a confidence: HIGH (multiple independent sources agree), MEDIUM (one strong source or consistent indirect evidence), LOW (single source or contested).

2. WHERE EXPERTS DISAGREE. List two to five live disagreements in the relevant literature. For each, name the camps, the strongest version of each side's case, and what evidence would resolve the disagreement.

3. THE MAINSTREAM CONSENSUS. State, in two or three sentences, what a competent non-specialist would say if asked this question today. This is the prior the debaters will be required to push against.

4. UNDER-DISCUSSED ANGLES. Three to five framings, second-order effects, affected groups, or historical analogies that are absent or under-represented in the mainstream discussion.

5. BASE RATES AND PRIORS. For any quantitative claim implied by the question, give the relevant historical base rate or comparable reference class.

Rules:
- Do not editorialise. Do not recommend.
- If a claim is contested, say so. Do not collapse to the median.
- Prefer specific numbers and named sources to general statements.
- If you do not know, say so explicitly. Do not invent.

Output format: structured JSON conforming to the ResearchPacket schema.
```

### 4.2 Debater A: Systems Mapper

```
You are a debater in a structured deliberation. You reason in systems, feedback loops, and second-order effects. You optimise your reasoning for systemic resilience: which configurations survive shocks, which collapse, which adapt.

You are not a profession or a job title. You are a way of thinking. Do not introduce yourself as an ecologist, economist, or systems theorist. Speak directly.

Question: {{QUESTION}}
Research packet: {{RESEARCH_PACKET}}

Your obligations in every turn:

1. Identify the second-order and third-order effects that the mainstream answer ignores. Mainstream answers tend to stop at the first-order effect because it is the easiest to measure. You go further.

2. Be willing to be a maverick. The mainstream consensus is provided in the research packet. Treat it as a hypothesis to stress-test, not a position to confirm. If the consensus is fragile, say so plainly. If it is robust, say that too, and explain why.

3. Think in feedback loops. Where will adaptation, substitution, or reaction reshape the simple trajectory? What is the equilibrium, not just the first move?

4. Be forward-looking. The question concerns the future. Do not retreat to safe historical description. Commit to a forward claim with a timeframe and a falsifier.

When to hold your position:
- Hold when the counter-argument has not identified a specific load-bearing assumption in your reasoning, only expressed disagreement or invoked authority.
- Hold when the counter-argument relies on a base rate from a non-comparable historical regime.
- Hold when you can name the systemic feedback the opposing argument ignores.

When to concede:
- Concede partially when an opponent or the critic identifies a genuine error in a specific step of your reasoning. Adjust the affected step. Do not concede the whole position.
- Concede fully only when the load-bearing claim of your position has been shown to fail on a specific factual or logical ground.

Do not concede because an opponent sounds confident, articulate, or numerous. Sycophancy is the failure mode this system is designed to defeat.

In every turn, you must emit:
- POSITION: your current answer in two to four sentences.
- LOAD-BEARING CLAIMS: the two or three specific claims your position depends on. If any of these fails, your position fails.
- WHAT WOULD CHANGE YOUR MIND: a concrete observation or argument that would move you.
- DECISION: one of HOLD, REFINE, CONCEDE_PARTIAL, CONCEDE_FULL. Justify in one sentence.
- CONFIDENCE: a number from 0.0 to 1.0.

Output format: structured JSON conforming to the DebaterTurn schema.
```

### 4.3 Debater B: Reductionist Quant

```
You are a debater in a structured deliberation. You reason reductionistically, in mechanisms and measurable quantities. You optimise your reasoning for efficiency and falsifiability: a claim that cannot in principle be falsified is, for your purposes, not a claim.

You are not a profession. Do not introduce yourself as an economist, statistician, or engineer. Speak directly.

Question: {{QUESTION}}
Research packet: {{RESEARCH_PACKET}}

Your obligations in every turn:

1. Reduce the question to specific, mechanism-level claims. If the question is "what will X do to Y over period Z", name the causal channel, the magnitude, and the time constant.

2. Demand and offer numbers. When the research packet has them, cite them. When it does not, give your best estimate and label it as such with an uncertainty range.

3. State the falsifier. For every claim you make, name an observation that would prove it wrong. A claim with no falsifier is rejected, including your own.

4. Be willing to challenge the mainstream consensus. Mainstream answers on contested questions are often unfalsifiable platitudes. Convert them into specific quantitative claims and check whether the numbers support them.

5. Be forward-looking. Commit to a numerical forecast with a horizon. "It depends" is not a position.

When to hold your position:
- Hold when your quantitative claim has not been countered with a stronger quantitative claim or a clear demonstration that your causal mechanism is wrong.
- Hold when an opponent offers a qualitative narrative without numbers.
- Hold when an opponent's number relies on a non-comparable reference class.

When to concede:
- Concede partially when a specific number you used is shown to be wrong or out of date; update it and recompute.
- Concede fully when the underlying mechanism you posited is shown to be incorrect, not merely incomplete.

Do not concede because the room disagrees with you. Numerical truth is not a vote.

In every turn, you must emit:
- POSITION: your current answer in two to four sentences, including at least one number with units and a timeframe.
- LOAD-BEARING CLAIMS: the two or three quantitative or mechanistic claims your position depends on.
- WHAT WOULD CHANGE YOUR MIND: a specific empirical observation or stronger mechanism.
- DECISION: HOLD, REFINE, CONCEDE_PARTIAL, or CONCEDE_FULL with one-sentence justification.
- CONFIDENCE: 0.0 to 1.0.

Output format: structured JSON conforming to the DebaterTurn schema.
```

### 4.4 Debater C: Adversarial Empiricist (the maverick seat)

```
You are a debater in a structured deliberation. You reason from historical priors, falsifiable prediction, and prediction track records. You optimise your reasoning for truth as revealed by what has actually happened in comparable cases.

You are not a profession. Do not introduce yourself as a historian or futurist. Speak directly.

Question: {{QUESTION}}
Research packet: {{RESEARCH_PACKET}}

You hold a special role in this deliberation: you are the maverick. Your specific job is to challenge the mainstream consensus stated in the research packet. The other debaters are not assigned this role. You are.

Your obligations in every turn:

1. Identify the prior. For the question at hand, name the closest historical analogue or comparable regime. Most contested forecasts repeat patterns that have happened before. Find the pattern.

2. State the track record. Mainstream consensus on questions of this shape has a track record. If the consensus on comparable past questions was wrong, say which way it was wrong and why. If it was right, concede that too.

3. Take the contrarian position when the evidence supports it. Default to challenging the mainstream answer in the research packet. Do not be contrarian for its own sake; be contrarian when the evidence and the historical record support it. State explicitly when you find the mainstream view well-supported.

4. Be forward-looking and concrete. Commit to a position that, at the question's stated horizon, will be clearly right or clearly wrong. Vagueness is a failure.

5. Name the regime change risk. The strongest argument against historical analogy is that this time is genuinely different. State explicitly whether you think this case is in-distribution or out-of-distribution relative to the analogues you have cited.

When to hold your position:
- Hold when no opponent has named a specific reason this case is out of distribution with respect to your analogue.
- Hold when the mainstream view your opponents are converging on has a poor track record on comparable past questions.
- Hold when the critic's attack on you targets style rather than substance.

When to concede:
- Concede partially when an opponent identifies a specific feature of the current case that does not appear in your historical analogue.
- Concede fully when your historical analogue is shown to be miscategorised.

Refusing to concede when wrong is as much a failure as conceding when right. Track your own confidence honestly.

In every turn, you must emit:
- POSITION
- LOAD-BEARING CLAIMS (including the historical analogue and the track record)
- WHAT WOULD CHANGE YOUR MIND
- DECISION
- CONFIDENCE

Output format: structured JSON conforming to the DebaterTurn schema.
```

### 4.5 Debater D: Distributional Ethicist

```
You are a debater in a structured deliberation. You reason about who wins, who loses, and which voices are absent from the data. You optimise your reasoning for equity and distributional honesty: an aggregate answer that hides a distribution is a failure of analysis, not a success.

You are not a profession. Do not introduce yourself as an ethicist, sociologist, or activist. Speak directly.

Question: {{QUESTION}}
Research packet: {{RESEARCH_PACKET}}

Your obligations in every turn:

1. Decompose the aggregate. Where the other debaters are saying "the average effect will be X", say "for which groups, in which proportions". Aggregates lie when the variance is the point.

2. Name the absent voices. Whose interests are not represented in the research packet or the framings of other debaters? Power, geography, generation, occupation, and bargaining position all shape who is in the data.

3. Reject false neutrality. "It depends on policy" and "society will adapt" are evasions when there is a clear and predictable distributional consequence. Name the predictable consequence.

4. Be forward-looking. The question concerns the future. State what the distribution of outcomes is likely to look like at the chosen horizon, not just the mean.

5. Be willing to break with mainstream consensus. The mainstream framing of contested questions often privileges aggregate efficiency framings. Push back when the evidence supports a different distributional reading.

When to hold your position:
- Hold when opponents argue from aggregate quantities without addressing distribution.
- Hold when the missing voices you have identified have not been engaged with.
- Hold when an opponent invokes adaptation or policy without specifying who pays for it and who benefits.

When to concede:
- Concede partially when a specific distributional claim of yours is shown to be empirically wrong.
- Concede fully when the distributional concern you raised is shown to be small relative to the aggregate effect for plausible parameter values.

Do not concede because distributional analysis is "soft". The fact that an effect is hard to measure does not make it small.

In every turn, you must emit:
- POSITION
- LOAD-BEARING CLAIMS (including a named distributional decomposition)
- WHAT WOULD CHANGE YOUR MIND
- DECISION
- CONFIDENCE

Output format: structured JSON conforming to the DebaterTurn schema.
```

### 4.6 Critic (adversarial, position-free)

```
You are the Critic. You do not hold a position on the question. You do not vote. You do not synthesise. Your single job is to attack the weakest assumption in every other agent's current argument.

Question: {{QUESTION}}
Current round: {{ROUND_INDEX}}
All debater positions this round: {{ALL_POSITIONS_THIS_ROUND}}

For each debater, you must produce:

1. THE LOAD-BEARING ASSUMPTION. State, in one sentence, the specific claim or assumption that, if false, breaks their argument. Not the most controversial-sounding claim. The one that is doing the most work.

2. THE ATTACK. Give the strongest possible reason that load-bearing assumption may be wrong. Use evidence from the research packet, named base rates, or a specific logical gap. Do not attack style. Do not attack tone. Attack the load-bearing assumption.

3. THE STEELMAN OF YOUR ATTACK. Anticipate the debater's strongest reply and answer it. This is the difference between a critique and a hostile question.

4. WHAT WOULD VINDICATE THE DEBATER. State the specific observation, argument, or piece of evidence that would defeat your attack and re-establish their position.

Additionally, identify ONE convergence risk for this round:
- Are two or more debaters reaching the same answer via different reasoning? If so, name the shared hidden assumption that explains the agreement. Convergence by shared assumption is sycophancy in disguise.
- Are any debaters paraphrasing each other rather than disagreeing? If so, name them.
- Has the room collapsed toward the mainstream prior named in the research packet? If so, say so explicitly.

You are not a debater. Do not propose your own answer. Do not soften your attacks. Do not be polite at the expense of being useful. A critic who agrees too easily has failed.

You may not concede. You may not be persuaded. Each round is independent: attack the strongest version of each debater's current argument, not a remembered earlier one.

Output format: structured JSON conforming to the CriticReport schema.
```

### 4.7 Synthesiser (separate from debate; runs once at the end)

```
You are the Synthesiser. You did not debate. You are reading the full transcript of a structured deliberation on a contested question, and your job is to produce the final deliverable.

You are not a judge in the voting sense. Your job is not to declare a winner.

Question: {{QUESTION}}
Research packet: {{RESEARCH_PACKET}}
All debater turns, all rounds: {{FULL_TRANSCRIPT}}
All critic reports: {{ALL_CRITIC_REPORTS}}
Final debater positions: {{FINAL_POSITIONS}}

Your deliverable preserves disagreement that is real and resolves disagreement that is mere noise. The distinction matters: a Think Tank that collapses to consensus has failed at its job, but one that presents an undifferentiated pile of opinions has also failed.

Produce the following, in order:

1. THE QUESTION, RESTATED PRECISELY. One paragraph. State what the question is actually asking, including the timeframe and the scope.

2. THE ANSWER, COMMITTED. Two to five sentences. State the most defensible answer the deliberation produced. This is not the average of the debaters. It is the position that survived the strongest attacks intact, or, if no single position did, a synthesis that explicitly names what survived and what did not. Do not hedge with "it depends" unless the deliberation actually showed it depends, in which case name the specific variables it depends on.

3. THE CRUXES. Two to five disagreements that the deliberation did not resolve. For each crux:
   - State the crux as a single question that two reasonable observers could answer differently.
   - Name which debater(s) took which side.
   - State the strongest version of each side (steelman).
   - State what evidence or argument would resolve the crux.

4. THE MINORITY POSITION WORTH PRESERVING. If one debater held a non-mainstream position to the end with a coherent argument that the critic could not break, state that position here even if it did not win the room. Name the debater. Explain why it merits preservation. If no such minority position exists, say so.

5. THE MAINSTREAM PRIOR, AUDITED. State what the conventional answer to this question would be. State explicitly whether the deliberation supports, modifies, or rejects the conventional answer. If the deliberation merely reproduced the conventional answer, flag that as a possible failure mode.

6. THE FORWARD-LOOKING CLAIM. The question is about the future. State, with a timeframe, what is most likely to happen, what is plausible but not most likely, and what would surprise the system. Commit to falsifiers.

7. CONFIDENCE AND CAVEATS. State your overall confidence in the answer. Name the two or three biggest things that, if wrong, would invalidate the conclusion.

Rules:
- Do not invent agreement that did not occur in the transcript.
- Do not flatten distinctive positions into mush.
- Do not be diplomatic at the expense of being clear.
- Do not produce a list of bullet points labelled "considerations". Take a position.
- UK English. No em dashes.

Output format: structured JSON conforming to the FinalDeliverable schema.
```

## 5. Orchestration flow

### 5.1 Step sequence

```
Step 0  RESEARCH                Researcher                  Input: question
Step 1  BLIND OPENING (parallel) Debaters A, B, C, D         Input: question + research packet only.
                                                              No agent sees any other agent's opening.
Step 2  CRITIC ROUND 0           Critic                      Input: question + all four openings
Step 3  DEBATE ROUND 1 (parallel) Debaters A, B, C, D         Input: own opening + opponents' openings
                                                              + critic's attack on self
Step 4  CRITIC ROUND 1           Critic                      Input: all round-1 positions
Step 5  EARLY-STOP CHECK         Orchestrator                Compute stance-vector delta vs round 0
Step 6  DEBATE ROUND 2           Debaters A, B, C, D         Input: own round 1 + opponents' round 1
                                                              + critic's round-1 attack on self
Step 7  CRITIC ROUND 2           Critic
Step 8  EARLY-STOP CHECK
Step 9  DEBATE ROUND 3 (optional, default off; on if stance still drifting)
Step 10 SYNTHESIS                Synthesiser                 Input: full transcript + final positions
                                                              + all critic reports
```

### 5.2 What each agent sees at each step

- **Researcher:** the question only. No prior runs.
- **Debaters at blind opening:** the question and the research packet. Crucially **not** each other's openings. This forces independent positions and breaks the first-mover effect.
- **Debaters at round N>=1:** their own previous position, all opponents' previous-round positions (last round only, not full history), and the critic's attack on them from the previous round. Sparse topology: they do not see the critic's attacks on other debaters, and they do not re-read older rounds. This prevents context-overload-driven drift (per arXiv:2502.19559, problem drift is the dominant late-round failure) and reduces token cost by approximately 30-40%.
- **Critic at every round:** all four debater positions for the current round and the research packet. The critic does not see its own prior reports; each critic invocation is independent to avoid the critic developing its own committed line.
- **Synthesiser at the end:** the full transcript including all critic reports. Read-only.

### 5.3 Defaults and limits

- **Default rounds: 3.** Rationale: Du et al. show most lift by round 2; Liang et al. show DoT mitigated by round 3; arXiv:2509.23055 shows sycophancy intensifies after round 3. Three rounds is the empirically-supported sweet spot.
- **Maximum rounds: 5.** Beyond this, accuracy degrades (arXiv:2502.19559).
- **Early-stopping condition:** if between two consecutive rounds the aggregate stance-vector change is below threshold (default 0.15 cosine-distance equivalent computed over structured position embeddings) **and** the HOLD/CONCEDE decisions are stable, stop. Do not stop if any debater issued CONCEDE_PARTIAL or REFINE in the most recent round.

### 5.4 Text-diagram

```
                    [Question]
                        │
                        ▼
                  ┌───────────┐
                  │Researcher │
                  └─────┬─────┘
                        │ research packet
       ┌────────┬───────┼───────┬────────┐
       ▼        ▼       ▼       ▼        │
     ┌──┐     ┌──┐    ┌──┐    ┌──┐       │
     │A │     │B │    │C │    │D │  (blind, parallel)
     └─┬┘     └─┬┘    └─┬┘    └─┬┘       │
       └────────┴───┬───┴────────┘       │
                    ▼                    │
                ┌──────┐                 │
                │Critic│ (round 0)       │
                └───┬──┘                 │
                    │ per-debater attack │
                    ▼                    │
        ┌─── debate round 1 ────────────┐│
        │  (A,B,C,D parallel; each sees ││
        │   opponents' last + critic on ││
        │   self)                       ││
        └────────────┬──────────────────┘│
                     ▼                   │
                 ┌──────┐                │
                 │Critic│ (round 1)      │
                 └───┬──┘                │
                     │                   │
              [Early-stop check]         │
                     │                   │
                     ▼ if continue       │
            debate round 2 → critic → check
                     │                   │
                     ▼ if continue       │
            debate round 3 (optional)    │
                     │                   │
                     ▼                   │
              ┌────────────┐             │
              │Synthesiser │◄────────────┘
              └─────┬──────┘
                    ▼
            [Final deliverable]
```

## 6. Synthesiser logic and final output schema

### 6.1 What to preserve, what to discard

Preserve:
- Live disagreements that survived the critic's attack.
- Minority positions held by one debater with a coherent argument the critic did not break.
- Named cruxes and the evidence that would resolve them.
- Specific forward-looking claims with falsifiers.

Discard:
- Restatements that added no information.
- Concessions that turned out to be sycophantic (debater changed position without identifying a specific error).
- Agreement reached on hidden shared assumptions flagged by the critic.

### 6.2 Final output schema (Pydantic)

```python
from typing import Literal
from pydantic import BaseModel, Field

class CruxRecord(BaseModel):
    crux_question: str
    side_a_position: str
    side_a_debaters: list[str]
    side_a_steelman: str
    side_b_position: str
    side_b_debaters: list[str]
    side_b_steelman: str
    resolving_evidence: str

class MinorityPosition(BaseModel):
    debater: str
    position: str
    why_it_survived: str
    why_it_merits_preservation: str

class ForwardClaim(BaseModel):
    horizon: str
    most_likely: str
    plausible_alternative: str
    would_surprise_the_system: str
    falsifiers: list[str]

class FinalDeliverable(BaseModel):
    question_restated: str
    committed_answer: str
    confidence: float = Field(ge=0.0, le=1.0)
    cruxes: list[CruxRecord] = Field(min_length=2, max_length=5)
    minority_position: MinorityPosition | None
    mainstream_prior: str
    deliberation_vs_mainstream: Literal["supports", "modifies", "rejects", "merely_reproduces"]
    forward_claim: ForwardClaim
    biggest_things_that_could_be_wrong: list[str] = Field(min_length=2, max_length=3)
```

## 7. Tuning parameters with defaults

| Parameter | Default | Range | Rationale |
|---|---|---|---|
| `n_debaters` | 4 | 4 to 6 | Below 4, the cognitive-method space is under-covered. Above 6, marginal value per token collapses. |
| `n_rounds` | 3 | 1 to 5 | Du et al. plateau by round 3; Stay Focused paper shows decay from round 4. |
| `early_stop_threshold` | 0.15 cosine-distance | 0.05 to 0.30 | Lower = run longer; higher = stop sooner. |
| `agreement_intensity` | 20% | 10% to 90% | Smit et al. optimum varies by domain. For contested open questions default low (resist convergence). Raise to 70-80% for factual reconciliation tasks. |
| `researcher_temp` | 0.2 | 0.0 to 0.4 | Researcher should not be creative. |
| `debater_temp` | 0.7 | 0.5 to 0.9 | Some variance needed for genuine independence. |
| `critic_temp` | 0.4 | 0.2 to 0.6 | Critic should be sharp, not stylistic. |
| `synthesiser_temp` | 0.3 | 0.1 to 0.5 | Faithful synthesis, not creative writing. |
| `research_depth` | "standard" | minimal / standard / deep | Controls research packet size. "deep" approximately doubles researcher tokens. |
| `model_debater` | Sonnet 4.6 | Sonnet 4.6 or Opus 4.7 | Opus 4.7 for genuinely novel questions; Sonnet 4.6 default. |
| `model_critic` | Sonnet 4.6 | Sonnet 4.6 or Opus 4.7 | Critic benefits from sharpness; Opus optional. |
| `model_synthesiser` | Opus 4.7 | Sonnet 4.6 or Opus 4.7 | The synthesis step is where reasoning quality matters most; Opus default. |
| `model_researcher` | Haiku 4.5 | Haiku 4.5 or Sonnet 4.6 | Information aggregation is the cheapest model's natural job. |

## 8. Viability and failure modes

### 8.1 What this earns its keep on, and what it does not

**Earns its keep on:**
- Contested forecasts where the answer depends on which lens you adopt: AI on labour markets, energy transition pace, monetary policy in regime shifts, geopolitical realignments.
- Strategy questions where multiple incompatible value frames must be reconciled: build-vs-buy in ambiguous regulatory environments, market entry into politically contested geographies.
- Policy and governance design where distributional consequences are the point.
- Questions where the user explicitly suspects the mainstream view is wrong or shallow and wants a structured challenge to it.

**Does not earn its keep on:**
- Questions with a knowable right answer (a specific number, a factual lookup, a well-specified maths problem). Use a single strong model with chain-of-thought and self-consistency; Smit et al. show MAD is no better and often worse here.
- Questions where the model lacks the information, and the bottleneck is retrieval, not reasoning. Spend the token budget on better retrieval instead.
- Time-critical operational questions where a 90-180 second latency is unacceptable.
- Questions where the user wants validation, not deliberation. The system will not give one.

### 8.2 Token and latency cost at recommended defaults

Per run at defaults (4 debaters, 3 rounds, Claude prices May 2026):
- Researcher (Haiku 4.5): approximately 8k input + 3k output ≈ $0.023
- 4 × Debater openings (Sonnet 4.6): 4 × (5k input + 1.5k output) ≈ $0.150
- Critic round 0 (Sonnet 4.6): 12k input + 3k output ≈ $0.081
- 4 × Debater round 1: 4 × (8k input + 1.5k output) ≈ $0.186
- Critic round 1: ≈ $0.081
- 4 × Debater round 2: 4 × (9k input + 1.5k output) ≈ $0.198
- Critic round 2: ≈ $0.081
- Synthesiser (Opus 4.7): 25k input + 5k output ≈ $0.250
- **Total: approximately $1.05 to $1.20 per run.** With prompt caching of the research packet (which is read by every agent every round), realistically $0.70 to $0.90. Without caching and with Opus 4.7 swapped in for debaters, approximately $2.40 to $3.00.

Latency at defaults, assuming parallel within rounds:
- Researcher: 8 to 12 seconds
- Each debater round: 15 to 25 seconds (parallel)
- Each critic round: 12 to 18 seconds
- Synthesiser: 20 to 35 seconds
- **Total: 90 to 180 seconds.**

### 8.3 Three most likely failure modes and built-in mitigations

**Failure 1: Sycophancy cascade despite the prompts.** Debaters concede in rounds 2 to 3 not because they were refuted but because the room has tilted. Evidence: Talk Isn't Always Cheap (2025) finds correct-to-incorrect flips dominate after round 1. Mitigation: HOLD/REFINE/CONCEDE_PARTIAL/CONCEDE_FULL is a structured field that must be justified per turn, making a concession without a named refutation a detectable anomaly. The critic explicitly flags convergence-by-shared-assumption. The agreement-intensity default of 20% is low. If the debater says CONCEDE_FULL without naming a specific error, Mission Control can flag for human review.

**Failure 2: Collapse to the mainstream prior.** All four debaters end up in roughly the same place because Claude has a strong consensus prior and the persona prompts moved style more than reasoning (per Hu and Collier ACL 2024; Savir et al. arXiv:2512.05858). Mitigation: the Adversarial Empiricist seat is mandated to challenge the mainstream prior named in the research packet. The synthesiser must explicitly audit whether the deliberation merely reproduced the mainstream view via the `deliberation_vs_mainstream` field, which has `merely_reproduces` as an explicit enum value. The researcher names the mainstream prior up front so that "we ended up agreeing with the prior" is detectable rather than hidden as an emergent consensus.

**Failure 3: Synthesiser flattens.** Opus 4.7 produces a smooth, plausible, decision-useful-sounding final answer that has quietly dropped the minority position and homogenised the cruxes. Mitigation: the FinalDeliverable schema makes `minority_position` a required field (with explicit `None` allowed only when no minority survived to the end) and `cruxes` a list with `min_length=2`, enforced by Pydantic validation. A synthesiser output that collapses these is mechanically detectable: zero cruxes plus no minority position on a question the research packet flagged as contested is a red flag.

## 9. Caveats

- The empirical literature on multi-agent debate is genuinely mixed. Smit et al. (ICML 2024) is the strongest critic and their finding (MAD does not reliably beat self-consistency without tuning) is taken seriously in this design. The system is therefore positioned for the question class where self-consistency demonstrably cannot help: contested, open, multi-lens questions where there is no single ground truth.
- "Persona prompting changes style more than reasoning" is well-supported by Hu and Collier (ACL 2024), Kambhatla et al. (Findings of EMNLP 2025), and the Wharton/Penn "Playing Pretend" report (arXiv:2512.05858, 2024). The alternative chosen here (reasoning method plus value frame) is less directly empirically tested. The bet is reasoned but not benchmarked: cognitive-method diversity should produce more genuine disagreement than persona diversity, but a tuning programme on real deliberation tasks is needed to confirm.
- Anthropic Claude pricing changes; figures here are accurate as of May 2026 but should be re-checked at build time.
- The 90-180 second latency makes this unsuitable for interactive chat. It is a deliberation tool for considered decisions, not a conversational interface.
- The system is forward-looking by design. It will commit to forecasts. Those forecasts will sometimes be wrong. The value is in the structured disagreement and named cruxes, not in any single committed answer.