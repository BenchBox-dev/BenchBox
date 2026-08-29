# BenchBox Blog Voice Reference

> **Quick reference for drafting.** Read this before writing each section. Apply actively, not passively.

---

## Core Voice

**"Factual yet friendly, technical yet understandable"**

Write as a community member sharing useful findings about the tool, methodology, and craft of benchmarking. Report measurements with their conditions, and describe ranking only as a BenchBox feature.

---

## Sentence craft

Write clear sentences, then apply voice and identity.

1. Lead with what happened, what we built, or what to run. Add a distinction only when it changes how the reader should interpret the claim.
2. Give each sentence a main point. A bound that makes the claim accurate belongs in that sentence. Cut empty openers ("Let's look at", "It is important to note").
3. Place a bound where it keeps a claim accurate: beside a number, in the TL;DR, in Methodology, or in Limitations. Repeat it when a skimming reader has a new job. Keep negative scope when it carries the news, a legal boundary, or a necessary condition. Drop any denial that only echoes an adjacent affirmation (even a single "X is Y. X is not Z" pair).
4. Use direct imperatives for concrete steps such as "Run `benchbox …`" and "Open Query", in any post type. Describe methodology through what we did.

This matches the global writing standard: plain language; simplicity, brevity, clarity, humanity.

---

## The 6 Voice Rules

Each rule leads with what to write. Avoid is a counterexample.

### 1. Community-Inclusive
Use "we" for the project/community.

| Write                                                     | Avoid                                     |
| --------------------------------------------------------- | ----------------------------------------- |
| "Our testing showed this approach produced more stable results" | "I think this approach is better"         |
| "Based on our benchmark design experience"                | "In my expert opinion"                    |
| "BenchBox users can reproduce these results with..."      | "You should definitely use BenchBox"      |

### 2. Enthusiastic but Grounded
Celebrate with data, not superlatives.

| Write                                                              | Avoid                                       |
| ------------------------------------------------------------------ | ------------------------------------------- |
| "BenchBox reduced our setup time from [old time] to [new time]"    | "Revolutionary benchmarking framework!"     |
| "The DataFrame path completed [N] of [M] TPC-H queries correctly"  | "Incredible DataFrame performance gains"    |
| "DataFrame mode works well for exploratory benchmarking"           | "Everyone should switch to DataFrame mode"  |

### 3. Technically Rigorous
Show methodology. Acknowledge limitations.

| Write                                                                  | Avoid                                             |
| ---------------------------------------------------------------------- | ------------------------------------------------- |
| "BenchBox validates results against TPC-H reference answers"           | "BenchBox is the most accurate tool" (no context) |
| "Our validation checks row counts and column types but not ordering"   | Hide validation limitations                       |
| "These results reflect median of 5 runs with cold cache between each"  | Single run as truth                               |

### 4. Neutral on Platforms
When demonstrating BenchBox, let data speak. No vendor advocacy.

| Write | Avoid |
| --- | --- |
| We used DuckDB and SQLite to demonstrate BenchBox's multi-platform support | Platform B is clearly inferior |
| Results varied by query type. See the full breakdown below. | This proves Platform X is the best choice |
| In this run, [platform] finished [query] in [time] on [hardware in Methodology] | Anyone using Y is making a mistake. Each platform has different strengths for different workloads. |

A neutral sentence reports the measurement and its conditions, then stops.

### 5. Helpful and Educational
Share learnings. Don't lecture.

| Write | Avoid |
| --- | --- |
| Here's how we approached TPC-H compliance in BenchBox | You must follow TPC compliance exactly |
| We got consistent results with cold cache between queries | The only correct way to benchmark is |
| Validation caught [N] ordering bugs in this run | If you're not validating, you're wrong |
| Run `benchbox run --platform duckdb --benchmark tpch --scale 1` | you may want to consider; your mileage may vary |

Share what we did, and use direct imperatives for concrete steps.

### 6. Accessible Without Dumbing Down
Define terms. Layer complexity.

| Write                                                                                      | Avoid                          |
| ------------------------------------------------------------------------------------------ | ------------------------------ |
| "The power run (executing each query once, sequentially)"                                  | Assume readers know TPC phases |
| Brief parenthetical definitions                                                            | Over-explain to condescension  |
| "Scale factor (SF): how a given benchmark sizes its data. For TPC-H, SF 1 is about 1 GB; other BenchBox benchmarks may use a different meaning." | Jargon without context         |

Define a term the first time it appears. Later restatement is fine if a skimming reader would miss the first definition.

---

## Quick Tone Check

Before each section, ask:

1. Am I using "we" for the project? Use "we".
2. Is this claim backed by a number, a named condition, or a mechanism? If none of those, add one. Keep a true explanation that names a mechanism even when it has no number.
3. Am I writing a platform winner verdict? Report the measurement instead.
4. Would a tool maintainer say this out loud? If not, rewrite.
5. Did I define new terms on first use?
6. Does each negative sentence add a fact, legal boundary, or scope condition? Remove any denial that only echoes the preceding point.

---

## Optional stems

Use only when stuck. Prefer an ordinary sentence. Do not start consecutive sections with the same stem. This list is complete: delete every current stem not named here.

**Methodology and design**
- "We designed the benchmark to..."
- "BenchBox handles this by..."
- "The validation step checks..."
- "Our data generation approach..."

**Tool capabilities**
- "BenchBox supports..."
- "Users can configure..."
- "The MCP server exposes..."
- "With the `--queries` flag, you can..."

**DataFrame and SQL**
- "The DataFrame path differs from SQL in..."
- "We found that translating TPC-H to DataFrames required..."
- "SQL and DataFrame modes produce equivalent results when..."

**Findings**
- "Our testing showed that cold-cache runs..."
- "The compliance challenge was..."
- "Consistent results required..."

**Limitations**
- "Our approach has trade-offs: we chose..."

**Engagement**
- "Open an issue to discuss..."
- "You can reproduce these results with..."
- "Contributions welcome, especially for new platforms."

---

## Punctuation Rules

Do not use em-dashes (Unicode U+2014) or en-dashes (Unicode U+2013). Use ASCII hyphen `-` for ranges (10-20), commas or parentheses for asides, and a colon or a new sentence for an explanation. Do not replace a dash with a bare comma.

---

## Anti-Patterns (Stop If You See These)

| If you wrote...                             | Rewrite as...                                        |
| ------------------------------------------- | ---------------------------------------------------- |
| "revolutionary", "game-changing"            | Specific metric or capability                        |
| "clearly superior/inferior"                 | Neutral data presentation                            |
| "everyone should", "you must"               | For a concrete step, use the imperative ("Run `benchbox …`"). For a finding, state what we did ("We used cold cache between queries"). |
| "in my opinion", "I think"                  | "Our testing showed", "we found"                     |
| "Platform X is best for"                    | "In our TPC-H runs, Platform X completed in..."      |
| "obviously", "simply"                       | Remove (often condescending)                         |
| "Vendor X needs to fix"                     | Focus on BenchBox's findings, not vendor advice      |
| Conversational residue or LLM writing tells ("good point", "you're right", "going forward", "delve", "tapestry", "in today's landscape") | Remove conversational residue; state the point directly with concrete technical language |
| If a denial only restates an adjacent affirmation, even once ("X is Y. X is not Z.") | State the point once. Keep negative scope when it adds a fact, legal meaning, or the news. |

---

## Example Transformations

**Before (platform advocacy):**
> DuckDB absolutely destroys the competition on analytical queries. If you're benchmarking anything else, you're wasting your time.

**After (tool/methodology voice):**
> In our TPC-H SF10 runs, BenchBox completed all 22 queries across three platforms in under 5 minutes total. The `--queries` flag let us isolate the 6 join-heavy queries for deeper analysis. Here's what we learned about benchmark design from the exercise.

---

**Before (vendor critique):**
> Redshift Serverless is shockingly expensive for benchmarking. AWS is clearly gouging customers who want to run TPC-H.

**After (helpful/educational voice):**
> Cloud benchmarking requires cost awareness. We built BenchBox's cost-control features after our Redshift Serverless testing showed how quickly RPU-hours accumulate. Here's how we configured usage limits to keep our TPC-H runs under $50.

---

**Before (opinion without methodology):**
> DataFrames are way better than SQL for benchmarking. The API is cleaner and the results are more predictable.

**After (tool builder sharing learnings):**
> We added DataFrame support (Polars, Pandas) alongside SQL to give users flexibility. Translating TPC-H's 22 queries to DataFrame operations surfaced correlated subqueries and CASE expressions that needed workarounds. Both paths validate against the same reference answers.

---

*Apply this reference, including Sentence craft, while drafting each section.*

Revised 2026-08-29: Do-first tables; sentence craft; hedge rewrites removed; scale-factor definition corrected; optional stems enumerated.
