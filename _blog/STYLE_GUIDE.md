# BenchBox Blog Style Guide

> A guide for writing technical blog posts that educate, inform, and engage the data engineering community with a friendly, OSS-community voice.

**Version**: 2.1
**Last Updated**: 2026-08-29

---

## Table of Contents

1. [Voice & Tone](#voice--tone)
2. [Content Principles](#content-principles)
3. [Post Structure](#post-structure)
4. [Technical Writing Guidelines](#technical-writing-guidelines)
5. [Code & Examples](#code--examples)
6. [Punctuation](#punctuation)
7. [Citations and Sources](#citations-and-sources)
8. [SEO & Metadata](#seo--metadata)
9. [Post Types](#post-types)
10. [Editorial Checklist](#editorial-checklist)

---

## Voice & Tone

The BenchBox voice is that of a **friendly community member sharing useful findings**. We're enthusiastic about what we've learned, rigorous about methodology, and neutral when comparing tools. We write so readers can make informed decisions.

### Core Voice: "Factual yet friendly, technical yet understandable"

Drafting card: [_blog/VOICE_REFERENCE.md](VOICE_REFERENCE.md), including Sentence craft. Do not copy that section into this file.

### Voice Characteristics

**1. Community-Inclusive**

Write as a fellow practitioner sharing discoveries with the community.

✅ **Do**:
- "We designed BenchBox's validation to check row counts, column types, and sort order..."
- "BenchBox users can reproduce these benchmarks with `benchbox run --platform duckdb --benchmark tpch`..."
- "Our testing of the DataFrame path showed that..."
- "The community has contributed platform adapters for..."

❌ **Don't**:
- "I think this approach is clearly better..."
- "In my expert opinion..."
- "You should definitely use..."

**2. Enthusiastic but Grounded**

Celebrate findings with genuine enthusiasm, backed by data. Avoid empty superlatives.

✅ **Do**:
- "We were excited to see the parallel data generator cut SF100 generation from 20 minutes to 8."
- "The new validation pipeline exceeded our expectations, catching 3 subtle ordering bugs we'd missed before."
- "This is a meaningful improvement for users benchmarking at scale factor 100 and above."

❌ **Don't**:
- "This is absolutely revolutionary and game-changing!"
- "The results were incredible and mind-blowing!"
- "Everyone should immediately switch to..."

**3. Technically Rigorous**

Show your work. Acknowledge limitations. Let methodology build credibility.

✅ **Do**:
- "BenchBox's power phase uses cold cache between queries."
- "BenchBox currently supports analytical benchmarks (TPC-H, TPC-DS, SSB, ClickBench). Transactional benchmarks are not yet supported."
- "Our DataFrame path has limitations: correlated subqueries and CASE expressions require manual translation."

Name hardware and overhead in Methodology; do not invent a number here.

❌ **Don't**:
- Make claims without specifying test conditions
- Hide limitations that affect interpretation
- Present single data points as universal truths

**4. Neutral on Platforms**

Report what the run shows about benchmarking. Ground every platform result in its conditions.

✅ **Do**:
- "We ran BenchBox against three platforms to demonstrate multi-platform support."
- "Results varied by query type. Aggregations and joins showed different patterns."
- "Each platform required different dialect translation in BenchBox's SQL layer."

❌ **Don't**:
- "Platform B is clearly inferior and should be avoided."
- "Vendor X backed the wrong horse and needs to pivot."
- "Anyone still using Y is making a mistake."
- "Each platform has different strengths for different workloads."

**5. Helpful and Educational**

Share concrete lessons as one practitioner to another. Invite readers to explore further.

✅ **Do**:
- "Here's what we learned about benchmark methodology from this exercise..."
- "Here's how we approached TPC-H compliance in BenchBox."
- "Open an issue to discuss."

❌ **Don't**:
- "You must follow TPC compliance exactly."
- "The only correct way to benchmark is..."
- "If you're not validating, you're wrong."
- "you may want to consider; your mileage may vary"

**6. Accessible Without Dumbing Down**

Layer explanations. Define terms naturally. Use examples to ground abstract concepts.

✅ **Do**:
- "Vectorized execution processes data in batches (typically 1,024 rows at a time) rather than row-by-row, reducing interpretation overhead."
- "TPC-H is a standard benchmark for analytical database performance, consisting of 22 queries that simulate business intelligence workloads."

❌ **Don't**:
- Assume readers know all acronyms
- Over-explain basics to the point of condescension
- Use jargon without context

### Tone by Content Type

| Content Type            | Tone                     | Example Opening                                                                             |
| ----------------------- | ------------------------ | ------------------------------------------------------------------------------------------- |
| **Architecture/Design** | Exploratory, educational | "BenchBox handles multi-platform dialect translation in the layers described below."        |
| **Methodology Guide**   | Rigorous, helpful        | "Here is the protocol we use for cold cache between runs."                                  |
| **Tutorial/How-To**     | Helpful, encouraging     | "Install BenchBox with `uv add benchbox`, then run TPC-H at SF 0.01 with the command below." |
| **BenchBox in Action**  | Curious, evidence-based  | "We ran TPC-H at SF10 across three platforms. Here's what we learned about benchmarking..." |
| **Release Notes**       | Celebratory, grateful    | "We're excited to release v0.2.0. Thanks to our 23 contributors..."                         |

### Voice Anti-Patterns to Avoid

**Marketing-Speak**
> ❌ "BenchBox is the revolutionary best-in-class benchmarking solution that leverages cutting-edge technology..."

**Platform Advocacy**
> ❌ "Database X is clearly failing and their team needs to wake up and fix their broken architecture."

**False Objectivity**
> ❌ "Objectively speaking, Platform A is superior in every way." (Opinion disguised as fact; present data, not platform verdicts)

**Hedging Everything**
> ❌ "It might possibly be the case that perhaps in some scenarios..." (Be clear about what you found)
> ❌ "This is not a certification. It is not a complete ranking. It does not claim..."
> ❌ "Each platform has different strengths for different workloads."
> ❌ "Your mileage may vary."
> ❌ "Platform results illustrate BenchBox. They are not a buying recommendation."
> ❌ "We are community members, not analysts."

State the finding once. Keep a negative bound only when it changes the claim or carries the news.

**Forced Humor**
> ❌ "OMG you won't BELIEVE these benchmark results! 🚀🔥 Database X got absolutely DESTROYED lol"

**LLM Writing Tells**
> ❌ "Good point! Going forward, let's delve into the ever-evolving data landscape..."
> ❌ "In today's fast-paced digital world..."
> ❌ "Whether you're a seasoned data engineer or just starting out..."
> ❌ "It stands as a testament to the seamless integration of..."

Avoid conversational residue ("good point", "you're right", "going forward"), empty throat-clearing openers ("in today's landscape"), and AI vocabulary clichés ("delve", "rich tapestry", "seamless"). State the technical finding or action directly.

---

## Content Principles

### 1. Lead with Data, Not Opinions

Lead with the point of the section. A measurement belongs in a results or methodology section; an architecture section may lead with the mechanism.

❌ **Don't**: "BenchBox is clearly the best benchmarking framework available."
✅ **Do**: "BenchBox completed TPC-H data generation and all 22 queries in under 10 minutes at SF1, with validation against reference answers."

**Every claim should be backed by**:
- Benchmark results with specific numbers
- Reproducible methodology
- Clear test parameters (scale factor, hardware, configuration)
- Links to raw data or detailed results

### 2. Be Transparent About Methodology

Every benchmark post should include:
- **Hardware specs**: CPU, RAM, storage type, cloud instance type
- **Software versions**: Database version, OS, driver versions
- **Configuration**: Non-default settings, tuning applied
- **Scale factors**: Data size, number of queries
- **Limitations**: What the test doesn't cover, known constraints

**Template**:
```markdown
## Test Environment

- **Hardware**: AWS c6i.4xlarge (16 vCPU, 32GB RAM, 500GB gp3 storage)
- **Database**: PostgreSQL 16.1 with default configuration
- **Benchmark**: TPC-H Scale Factor 10 (10GB)
- **Methodology**: Median of 5 runs, cold cache between runs
- **Limitations**: Single-node only, no concurrent workload simulation
```

### 3. Show Your Work

Readers should be able to reproduce your results.

**Always provide**:
- Links to BenchBox GitHub repo with configs
- Specific commands used to run benchmarks
- SQL queries tested (or reference to standard benchmark)
- Data generation steps
- Any preprocessing or setup required

**Example**:
```markdown
All tests were run using BenchBox:

$ benchbox run --platform duckdb --benchmark tpch --scale 10 \
  --phases load,power --output results/duckdb-tpch-sf10

Full configuration and raw results: [link to GitHub]
```

### 4. Explain the Trade-offs

❌ **Don't**: "SQL mode is better than DataFrame mode."
✅ **Do**: "SQL mode covers all queries in the spec set. DataFrame mode covers [N] of [M] queries and [named gain, with a number or condition]."

**Always discuss**:
- When a reader should choose each approach, with a number or named condition
- Trade-offs (compliance vs flexibility, setup cost vs reproducibility)
- When results might differ (scale factor, platform, configuration)

### 5. Celebrate the Community

Acknowledge contributors, highlight community work, invite participation.

- "Thanks to contributor @username for this improvement..."
- "This finding came from a community discussion in issue #123..."
- "We'd love your feedback. Join the discussion at..."

---

## Post Structure

### Standard Post Format

```markdown
# [Clear, Specific Title]

> [One-sentence summary of what readers will learn]

**TL;DR**: [2-3 sentence summary]

The pull quote and TL;DR state the finding. A bound belongs there when the summary would be misleading without it. Negative scope is allowed when it is the finding ("Two timings still have to earn a comparison").

---

## Introduction

- What question we're exploring
- Why it matters
- What readers will learn

## [Main Content Sections]

### Section 1: [Descriptive Heading]
[Content with data and examples]

### Section 2: [Descriptive Heading]
[Content]

## Results

[Data presentation with charts/tables]

## Analysis

[What the results mean, trade-offs, context]

## Methodology

[How we ran the tests, be thorough]

## Limitations

[What this doesn't test, known constraints]

## Conclusions

[Summary, key takeaways]

## Next Steps

[What readers can do, how to reproduce, invitation to discuss]

---

## References

[Footnotes and links]

*Questions or feedback? [Open an issue](link) or join the discussion.*
```

### Section Lengths (Guidelines)

| Section          | Target Length  | Purpose           |
| ---------------- | -------------- | ----------------- |
| **Introduction** | 150-300 words  | Hook and context  |
| **Main Content** | 800-1500 words | Core analysis     |
| **Methodology**  | 200-400 words  | Reproducibility   |
| **Results**      | 300-600 words  | Data presentation |
| **Conclusions**  | 150-250 words  | Takeaways         |

**Total post length**: 1,500-3,000 words for benchmark posts, 800-1,200 for tutorials.

---

## Technical Writing Guidelines

### 1. Precision in Language

**Be specific about numbers**:
- ❌ "much faster"
- ✅ "Data generation completed in 45s at SF10 (8 tables, 86M total rows)"

**Use concrete metrics**:
- ❌ "better performance"
- ✅ "Validation overhead: 0.3s per query (< 1% of typical execution time)"

**Quantify scale**:
- ❌ "large dataset"
- ✅ "TPC-H SF100: 600M+ rows across 8 tables, 23GB in Parquet format"

### 2. Define Technical Terms

Define a term the first time it appears. Restate later if a skimming reader would miss the first definition.

```markdown
BenchBox measures how vectorized execution (processing data in batches of
1,024-2,048 rows rather than one at a time) affects TPC-H query performance...
```

### 3. Active Voice

Prefer active voice for clarity:
- ❌ "The benchmark was run five times"
- ✅ "We ran the benchmark five times"

### 4. Headings

Use heading levels logically:

```markdown
# Post Title (H1 - only one per post)
## Major Section (H2)
### Subsection (H3)
#### Minor Point (H4 - use sparingly)
```

**Heading Style**:
- Use sharp, descriptive phrases or sentence-style headings that name the section's point (for example: `## The problem: SF=1 meant nothing in particular`).
- A title or heading whose news is a negation is allowed (for example: `# When two timings are not a comparison`).
- Do not use first-person headings:
  - ❌ "How I optimized query performance"
  - ✅ "Optimizing Query Performance"
- Avoid empty or clever headings that obscure the content.

---

## Code & Examples

### Code Blocks

Always specify the language for syntax highlighting:

```sql
SELECT customer_name, SUM(revenue) as total
FROM orders
WHERE order_date >= '2024-01-01'
GROUP BY customer_name
ORDER BY total DESC
LIMIT 10;
```

### Command Examples

Show the command and representative output:

```bash
$ benchbox run --platform duckdb --benchmark tpch --scale 1

BenchBox v0.1.0
Platform: DuckDB 0.10.0
Benchmark: TPC-H SF1

[INFO] Loading data...
[INFO] Running queries...
[SUCCESS] Completed in 42.3s
```

Use `$` to denote the prompt (readers won't copy it by accident).

### Inline Code

Use backticks for:
- Command names: `benchbox`, `duckdb`
- File names: `config.yaml`, `results.json`
- Variable names: `scale_factor`, `query_time`
- Short code: `SELECT * FROM table`

Don't use for:
- Product names: DuckDB (not `DuckDB`)
- Emphasis: Use **bold** or *italic*

---

## Punctuation

### Em-dashes and En-dashes

Do not use em-dashes (Unicode U+2014) or en-dashes (Unicode U+2013) in BenchBox content. These characters create inconsistency across text editors, copy-paste operations, and rendering contexts. Use ASCII hyphen `-` for ranges (10-20), commas or parentheses for asides, and a colon or a new sentence for an explanation. Do not replace a dash with a bare comma.

| Character | Unicode | Status       |
| --------- | ------- | ------------ |
| Em-dash   | U+2014  | ❌ Prohibited |
| En-dash   | U+2013  | ❌ Prohibited |
| Hyphen    | U+002D  | ✅ Allowed    |

### Alternatives

| Instead of                         | Use                   | Example                                |
| ---------------------------------- | --------------------- | -------------------------------------- |
| Em-dash or en-dash aside           | Commas or parentheses | "Parenthetical, like this, works well" |
| Em-dash introducing an explanation | Colon or a new sentence | "A statement:"                       |
| Number range written with en-dash  | ASCII hyphen          | "10-20"                                |
| Attribution with em-dash           | Colon or comma        | "Attribution: Author"                  |

**Why this rule?** Plain ASCII punctuation is more portable, accessible, and consistent across all editing environments and platforms.

---

## Citations and Sources

### What Requires Citation

| Category                     | Example                                             | Citation Required          |
| ---------------------------- | --------------------------------------------------- | -------------------------- |
| **External specifications**  | "The TPC-H spec requires ordered results for Q1..." | ✅ Yes                      |
| **Cloud pricing**            | "$0.36/RPU-hour for Redshift Serverless"            | ✅ Yes                      |
| **Platform documentation**   | "DuckDB v0.10 added parallel CSV reading"           | ✅ Yes                      |
| **Hardware specifications**  | "c6i.4xlarge: 16 vCPU, 32GB RAM"                    | ✅ Yes                      |
| **Our own BenchBox results** | "In our testing..."                                 | ❌ No (link to methodology) |
| **Common knowledge**         | "SQL is a query language"                           | ❌ No                       |

### Citation Format

Use Markdown footnotes:

```markdown
Redshift Serverless charges $0.36 per RPU-hour[^1].

[^1]: [Amazon Redshift Pricing](https://aws.amazon.com/redshift/pricing/) - AWS, accessed January 2026
```

### Footnote Content

```markdown
[^n]: [Descriptive Link Text](URL) - Source, Date (if relevant)
```

---

## SEO & Metadata

### Title Optimization

**Good titles are**:
- Specific: Include numbers, platform names, benchmark names
- Honest: Don't overpromise
- Under 60 characters

**Formulas**:
- "How BenchBox Handles [Technical Challenge]"
- "[Benchmark] at [Scale]: Lessons in Benchmark Design"
- "How to [Task] with BenchBox"
- "[Feature]: Building [Capability] into BenchBox"

### Meta Description

150-160 character summary:

```markdown
meta_description: "How we designed BenchBox's TPC-H validation pipeline
to catch subtle result differences across platforms. Methodology and lessons learned."
```

### Tags

Include 5-8 relevant tags:
- Benchmark: `tpc-h`, `tpc-ds`, `ssb`, `clickbench`
- Features: `dataframe`, `mcp`, `validation`, `cost-controls`
- Topics: `benchmarking`, `methodology`, `architecture`, `tutorial`
- Platforms (when relevant): `duckdb`, `polars`, `snowflake`

---

## Post Types

### 1. Architecture/Design Post

**Purpose**: Explain how BenchBox works internally
**Length**: 1,500-2,500 words
**Tone**: Exploratory, educational

**Essential elements**:
- Clear concept introduction
- Progressive complexity (overview → internals)
- Diagrams/visualizations of system design
- Code examples showing the design in action
- Why we made specific architectural choices
- Trade-offs acknowledged

**Example topics**:
- How BenchBox translates SQL across dialects
- The validation pipeline: reference answers to pass/fail
- Multi-phase benchmark execution design
- How the MCP server exposes benchmarking to AI agents

### 2. Methodology Guide

**Purpose**: Teach benchmark design concepts using BenchBox as illustration
**Length**: 1,500-2,500 words
**Tone**: Rigorous, helpful, educational

**Essential elements**:
- Clear methodological question being explored
- Specific BenchBox configuration examples
- Data showing why methodology matters (variance, consistency)
- Limitations of the approach
- References to TPC standards where relevant

**Example topics**:
- Cold cache vs warm cache: when each matters
- Scale factor selection: matching your hardware
- Benchmark compliance vs practical benchmarking
- Handling variance: median, percentiles, and outliers

### 3. Tutorial/How-To Post

**Purpose**: Help users accomplish specific tasks with BenchBox
**Length**: 800-1,500 words
**Tone**: Helpful, step-by-step, encouraging

**Essential elements**:
- Clear prerequisites
- Step-by-step instructions with BenchBox commands
- Expected output at each step
- Common issues and fixes
- Next steps for deeper exploration

**Example topics**:
- Running your first TPC-H benchmark
- Adding a new platform to BenchBox
- Using the MCP server for AI-driven benchmarking
- Configuring cloud cost controls for Redshift/Snowflake

### 4. Technical Challenge Post

**Purpose**: Share interesting problems and solutions in benchmark tooling
**Length**: 1,500-2,500 words
**Tone**: Curious, problem-solving, community-oriented

**Essential elements**:
- Clear problem statement
- What we tried (including what didn't work)
- The solution and why it works
- Lessons learned for others facing similar challenges
- Code examples

**Example topics**:
- Translating TPC-H to DataFrame operations
- Handling TPC-DS data generation at fractional scale factors
- Validating results across platforms with different type systems
- Compression trade-offs for benchmark data

### 5. BenchBox in Action Post

**Purpose**: Demonstrate BenchBox's capabilities through real benchmark runs
**Length**: 2,000-3,000 words
**Tone**: Curious, evidence-based, neutral on platform performance

**Essential elements**:
- Clear question about benchmarking methodology
- BenchBox commands used, fully reproducible
- Results presented neutrally (no platform advocacy)
- Focus on what we learned about the benchmarking process
- Methodology details and limitations

**Important**: Use platform results to illustrate BenchBox methodology and reporting, with enough conditions for readers to interpret each measurement.

**Example topics**:
- Running TPC-H at scale: what happens from SF1 to SF100
- Cloud benchmarking with cost controls: a practical walkthrough
- DataFrame vs SQL: comparing BenchBox execution paths
- Multi-platform runs: BenchBox's dialect translation in practice

### 6. Release Notes

**Purpose**: Announce new versions, thank contributors
**Length**: 500-1,000 words
**Tone**: Celebratory, grateful, informative

**Essential elements**:
- Version number and date
- Headline improvements
- Contributor acknowledgments
- Migration notes if applicable
- Link to full changelog

---

## Editorial Checklist

### Content Quality

- [ ] Clear purpose and question being answered
- [ ] Data-backed claims with specific numbers
- [ ] Methodology detailed enough to reproduce
- [ ] Limitations explicitly stated
- [ ] All links tested and working
- [ ] Code examples tested and working

### Voice & Tone

- [ ] Community-inclusive language ("we", not "I")
- [ ] Enthusiastic but grounded (data over superlatives)
- [ ] Neutral on platforms (no platform advocacy or vendor criticism)
- [ ] Helpful framing (sharing learnings, not lecturing)
- [ ] Accessible explanations (terms defined, examples given)
- [ ] How-to and Try-it-yourself steps use direct imperatives ("Run", "Open")
- [ ] Em-dashes and en-dashes are absent (ASCII hyphen only)
- [ ] Every negative bound adds a fact, legal boundary, or scope condition
- [ ] Ensure that agent work on our writing (e.g. reviews, style checks, etc.) has not added LLM writing tells to our work

### Technical Accuracy

- [ ] Methodology sound and documented
- [ ] Environment specified (hardware, software, config)
- [ ] Results reproducible with provided commands
- [ ] Statistics correct and verified
- [ ] Versions specified for all software
- [ ] Limitations clear and honest

### Formatting

- [ ] Heading hierarchy correct (H1 → H2 → H3); headings name the section's point without first-person pronouns
- [ ] Code formatted with language specified
- [ ] Tables readable and not too wide
- [ ] Numbers formatted consistently

### Citations

- [ ] External facts have footnotes
- [ ] URLs verified and working
- [ ] Sources are authoritative
- [ ] Pricing/dates noted where relevant

### SEO & Metadata

- [ ] Title specific and under 60 characters
- [ ] Meta description 150-160 characters
- [ ] URL slug descriptive
- [ ] Tags added (5-8)

---

## Voice Reference (Quick Reference)

For a condensed voice guide during drafting, see: `_blog/VOICE_REFERENCE.md`

---

## Attribution

This style guide is informed by analysis of OSS blog best practices from:
- [DuckDB](https://duckdb.org/news/)
- [Apache Arrow](https://arrow.apache.org/blog/)
- [Apache DataFusion](https://datafusion.apache.org/blog/)
- [Polars](https://pola.rs/posts/)
- [Trino](https://trino.io/blog/)
- [ClickHouse](https://clickhouse.com/blog)

---

## Revision History

| Version | Date       | Changes                                                                                                        |
| ------- | ---------- | -------------------------------------------------------------------------------------------------------------- |
| 2.1     | 2026-08-29 | Voice examples lead with what to write. Sentence craft lives in VOICE_REFERENCE. Hedge rewrites removed. Punctuation glyphs described by codepoint. Publishing steps no longer call a missing validator. |
| 2.0     | 2026-01-22 | Complete rewrite for OSS community voice. Removed analyst/commentator tone. Added neutral comparison guidance. |
| 1.2     | 2025-12-15 | Voice characteristics (removed from this guide)                                                                |
| 1.1     | 2025-12-02 | Citations section                                                                                              |
| 1.0     | 2025-11-23 | Initial guide                                                                                                  |

---

*Last updated: 2026-08-29*
