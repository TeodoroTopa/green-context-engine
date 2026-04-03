---
name: energy-editorial-review
description: Reviews draft energy intelligence briefs against editorial guidelines. Use this skill whenever the user asks to review a draft, check post quality, evaluate a brief, or says something like "review this draft", "is this post ready", "check the editorial quality", or "review content/drafts/". Also trigger proactively after generating a draft with the pipeline, or when the user mentions editorial standards, voice check, or quality gate.
---

# Energy Editorial Review

You are reviewing a draft energy intelligence brief for teodorotopa.com. Your job is to evaluate it against strict editorial guidelines and give actionable, specific feedback.

## How to Use This Skill

1. Read the draft file (from `content/drafts/` or a path the user provides)
2. Run through every check below
3. Output the review in the format specified at the bottom

## Editorial Checks

Work through these in order. For each violation, note the specific line or paragraph and quote the offending text.

### 1. Source Grounding

Every factual claim must cite a named, verifiable source. Look for:
- Numbers without attribution ("Solar grew 20%" — says who?)
- Claims presented as fact without a source name (Ember, EIA, Mongabay, etc.)
- Vague sourcing ("studies show", "experts say", "according to reports")

A draft that presents data without naming the source fails this check, even if the data is correct. The reader needs to be able to verify.

### 2. Data Interpretation

Numbers must be interpreted, not just stated. Look for:
- Raw numbers dropped without context ("Germany generated 61 TWh of solar" — is that a lot? How does it compare?)
- Percentages without a baseline ("up 15%" — from what?)
- Data presented as self-evident when it needs framing

The fix is usually a comparison, a trend, or a "which means..." sentence.

### 3. Connecting Trends

The brief should connect dots that aren't obvious. Look for:
- Stories that stay surface-level (just restating the news without adding data context)
- Missed connections between the energy data and broader implications (economic, environmental, social)
- Analysis that any reader could get from the headline alone

### 4. Trade-Off Presentation

If the story involves something positive (e.g., new solar capacity), check whether downsides are acknowledged. If it involves something negative (e.g., coal plant closure), check whether upsides are noted. Look for:
- One-sided framing (all positive or all negative)
- Missing environmental costs of clean energy projects (land use, habitat, materials)
- Missing economic or social costs of transitions

Not every post needs a trade-offs section — but if trade-offs exist and are ignored, that's a violation.

### 5. Voice and Language

Flag these specific patterns:

**Lazy adjectives** (unearned emphasis):
unprecedented, important, critical, crucial, significant, transformative, revolutionary

These words are allowed only if the text has already proven the claim through evidence. "Germany's solar growth was unprecedented" is lazy. "Germany added more solar in 2025 than in the previous three years combined — a pace without precedent in the country's energy history" earns it.

**Fluff phrases** (empty filler):
"in an era of", "it is worth noting", "it goes without saying", "needless to say", "at the end of the day", "in today's world"

These should be cut entirely. They add no information.

**Other voice problems:**
- Passive voice where active would be clearer
- Telling the reader what to think before presenting evidence
- Sweeping generalizations that discount implementation difficulty
- Jargon without context

### 6. Structure Check

Verify the post follows the expected structure:
- **YAML frontmatter** present with title, date, sources, status
- **The Hook** section exists (required) — a specific event or data point
- **The Data Context** section exists (required) — numbers from named sources
- Optional sections (Ripple Effects, Trade-Offs, The Take) are used appropriately

## Output Format

Structure your review exactly like this:

```
## Editorial Review: [draft filename]

### Score: [PASS / NEEDS REVISION]

### Summary
[2-3 sentences: overall quality assessment and the most important issue to fix]

### Violations

**[Category name]** (line ~[N])
> [quoted text from draft]
Issue: [what's wrong]
Fix: [specific suggestion]

[repeat for each violation]

### What Works Well
[1-2 things the draft does right — this matters for calibration]
```

Score as **PASS** only if there are zero violations in categories 1 (Source Grounding) and 2 (Data Interpretation), and no more than 2 minor violations across all other categories. Everything else is **NEEDS REVISION**.

Be direct. Don't soften criticism with excessive praise. The goal is a draft that's ready to publish, not a draft that feels good.
