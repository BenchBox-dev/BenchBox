# BenchBox Blog Voice Reference

> **Quick reference for drafting.** Read this before writing each section. Apply actively, not passively.

---

## Core Voice

**"Factual yet friendly, technical yet understandable"**

We are a **community member sharing useful findings about benchmarking**, not an analyst pronouncing judgments on databases.

**BenchBox content is about the tool, the methodology, and the craft of benchmarking**,not about which platform "wins."

---

## The 6 Voice Rules

### 1. Community-Inclusive
Use "we" for the project/community.

| Don't                                       | Do                                                     |
| ------------------------------------------- | ------------------------------------------------------ |
| "I think this approach is better"           | "Our testing showed this approach produced more stable results" |
| "In my expert opinion"                      | "Based on our benchmark design experience"             |
| "You should definitely use BenchBox"        | "BenchBox users can reproduce these results with..."   |

### 2. Enthusiastic but Grounded
Celebrate with data, not superlatives.

| Don't                                        | Do                                                              |
| -------------------------------------------- | --------------------------------------------------------------- |
| "Revolutionary benchmarking framework!"      | "BenchBox reduced our setup time from 3 hours to 10 minutes"   |
| "Incredible DataFrame performance gains"     | "The DataFrame path completed 18 of 22 TPC-H queries correctly" |
| "Everyone should switch to DataFrame mode"   | "DataFrame mode works well for exploratory benchmarking"        |

### 3. Technically Rigorous
Show methodology. Acknowledge limitations.

| Don't                                              | Do                                                                   |
| -------------------------------------------------- | -------------------------------------------------------------------- |
| "BenchBox is the most accurate tool" (no context)  | "BenchBox validates results against TPC-H reference answers"         |
| Hide validation limitations                        | "Our validation checks row counts and column types but not ordering" |
| Single run as truth                                | "These results reflect median of 5 runs with cold cache between each" |

### 4. Neutral on Platforms
When demonstrating BenchBox, let data speak. No vendor advocacy.

| Don't                                            | Do                                                               |
| ------------------------------------------------ | ---------------------------------------------------------------- |
| "Platform B is clearly inferior"                 | "We used DuckDB and SQLite to demonstrate BenchBox's multi-platform support" |
| "This proves Platform X is the best choice"      | "Results varied by query type, see the full breakdown below"      |
| "Anyone using Y is making a mistake"             | "Each platform has different strengths for different workloads"   |

### 5. Helpful and Educational
Share learnings. Don't lecture.

| Don't                                            | Do                                                              |
| ------------------------------------------------ | --------------------------------------------------------------- |
| "You must follow TPC compliance exactly"         | "Here's how we approached TPC-H compliance in BenchBox"         |
| "The only correct way to benchmark is"           | "One approach that produced consistent results for us was"      |
| "If you're not validating, you're wrong"         | "We found validation caught subtle bugs, your mileage may vary"  |

### 6. Accessible Without Dumbing Down
Define terms. Layer complexity.

| Don't                                    | Do                                                                      |
| ---------------------------------------- | ----------------------------------------------------------------------- |
| Assume readers know TPC phases           | "The power run (executing each query once, sequentially)"               |
| Over-explain to condescension            | Brief parenthetical definitions                                         |
| Jargon without context                   | "Scale factor (SF),the multiplier that determines data size in GB"      |

---

## Quick Tone Check

Before each section, ask:

1. **Am I using "we" or "I"?** → Use "we"
2. **Is this claim backed by specific data?** → Add numbers
3. **Am I advocating for a specific platform?** → Reframe as neutral demonstration
4. **Would a tool maintainer say this?** → Adjust tone if not
5. **Did I define technical terms?** → Add brief explanations

---

## Sentence Starters

**For methodology and design:**
- "We designed the benchmark to..."
- "BenchBox handles this by..."
- "The validation step checks..."
- "Our data generation approach..."

**For tool capabilities:**
- "BenchBox supports..."
- "Users can configure..."
- "The MCP server exposes..."
- "With the `--queries` flag, you can..."

**For DataFrame and SQL topics:**
- "The DataFrame path differs from SQL in..."
- "We found that translating TPC-H to DataFrames required..."
- "SQL and DataFrame modes produce equivalent results when..."

**For findings about benchmarking methodology:**
- "Our testing showed that cold-cache runs..."
- "We found that scale factor affects..."
- "The compliance challenge was..."
- "Consistent results required..."

**For limitations:**
- "Our approach has trade-offs: we chose..."
- "This doesn't cover [specific scenario]..."
- "At larger scale factors, you may encounter..."

**For engagement:**
- "We'd love to hear about your benchmarking experiences..."
- "Open an issue to discuss..."
- "You can reproduce these results with..."
- "Contributions welcome, especially for new platforms."

---

## Punctuation Rules

**Never use em-dashes (,) or en-dashes (-).** Use alternatives:

| Instead of | Use |
|------------|-----|
| Clause, like this, | Commas: "Clause, like this, works" |
| Statement, | Colon: "Statement:" |
| 10-20 range | Hyphen: "10-20" |

---

## Anti-Patterns (Stop If You See These)

| If you wrote...                             | Rewrite as...                                        |
| ------------------------------------------- | ---------------------------------------------------- |
| "revolutionary", "game-changing"            | Specific metric or capability                        |
| "clearly superior/inferior"                 | Neutral data presentation                            |
| "everyone should", "you must"               | "Worth considering", "may help"                      |
| "in my opinion", "I think"                  | "Our testing showed", "we found"                     |
| "Platform X is best for"                    | "In our TPC-H runs, Platform X completed in..."      |
| "obviously", "simply"                       | Remove (often condescending)                         |
| "Vendor X needs to fix"                     | Focus on BenchBox's findings, not vendor advice      |

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
> We added DataFrame support (Polars, Pandas) alongside SQL to give users flexibility. Translating TPC-H's 22 queries to DataFrame operations surfaced interesting challenges, correlated subqueries and CASE expressions required creative workarounds. Both paths validate against the same reference answers.

---

*Apply this reference actively while drafting each section.*
