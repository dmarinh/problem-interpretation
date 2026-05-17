# PTM Retrieval Investigation — Demo Narrative

For the advisory board. ~5-minute walkthrough. Tells the story of two experiments, their findings, and the recommendation, without requiring ML background.

---

## The question

PTM works by looking up food properties — pH, water activity — in a knowledge base. When a user asks about chicken, the system needs to find the row that says "chicken: pH 6.2 to 6.4". The component that does this lookup is called an **embedder**: it turns words into numbers in a way that lets the system find similar entries.

Production today uses a small, fast embedder called MiniLM. It mostly works — but we'd noticed a specific failure mode: when users ask about species like "turkey" or "lamb", the system often fails to find the right row, even though the right row exists in the knowledge base under a category name like "fresh poultry" or "fresh meat".

So the question we set out to answer: **is there a better embedder we should switch to?**

That turned into two experiments. The second one gave us an answer we didn't expect.

---

## Experiment 2.1 — what we tested

We tested four embedders against the same problem:

- MiniLM (current production) — small, general-purpose
- BGE small — same size as MiniLM, but specifically trained for search
- BGE base — 5× bigger, also trained for search
- mpnet — 5× bigger, general-purpose

We gave each one 30 test queries spanning four difficulty levels:

- **Easy** — foods that have their own row in the knowledge base (chicken, white bread, milk). All embedders should handle these.
- **Medium** — species queries that need to match a category row (turkey → fresh poultry). This is where MiniLM fails.
- **Hard** — negative controls. Queries with no correct answer, like the made-up food "zarblax burger". The right behaviour is silence — no match.
- **Pathogen** — hazard lookups. A sanity check; all embedders should pass.

## What we found

No single embedder was clearly better. Each had a different failure pattern:

- MiniLM (baseline) — weak on species queries (medium), perfect on negative controls (hard).
- BGE small — best on easy queries, but **failed every negative control** — it would confidently match nonsense queries to unrelated docs.
- BGE base — actually worse on average, despite being 5× larger.
- mpnet — highest accuracy, but also failed one negative control.

**The recommendation: do not switch.** A wrong answer that comes with high confidence is more dangerous than no answer at all. PTM's safety design depends on the system saying "I don't know" rather than guessing.

---

## What we learned that mattered more

Exp 2.1 told us *no* embedder fixed the species-probe problem at the production threshold. But that left us wondering — maybe the problem isn't the embedder. Maybe it's how we use it.

So we ran a second experiment.

---

## Experiment 2.2 — what we changed

Three changes:

**1. Doubled the test queries.** From 30 to 60. Added more species probes, more negative controls, including bare-class queries like just "meat" or just "fish" — the kind of thing users actually type.

**2. Tested a second variable: doc text format.** Each row in our knowledge base gets turned into a string before the embedder sees it. We tested three styles — terse (keywords only), current (production), verbose (full sentences). 4 embedders × 3 formats = 12 combinations.

**3. Calibrated thresholds per combination.** Instead of using one fixed threshold for everyone, each combination gets its own threshold tuned to be both accurate and safe.

## What we found

**The headline:** doc text format moves accuracy as much as embedder choice does.

Going from terse to verbose format improves retrieval by 0.20–0.30 across all four embedders — a bigger effect than switching between any two embedders at the same format.

**The recommendation:** keep MiniLM, adopt the verbose format. This pairs the smallest model with the format that works best for it. The improvement over baseline is small but consistent, and verbose is the best format for three of the four embedders we tested.

---

## What we learned that we didn't expect

The most interesting finding wasn't about which embedder to pick. It was about *what's actually breaking*.

When we looked carefully at the species-probe queries — turkey, duck, lamb — we found something surprising. **MiniLM was ranking the right answer at #1 most of the time.** For 16 out of 20 medium-stratum queries, the canonical doc was already the top match.

The problem wasn't retrieval. The problem was the **gate** — the confidence threshold the system uses to decide whether to accept a match. The canonical doc's confidence score sits right around 0.50–0.66, and the production gate is 0.62. So the system finds the right answer, then filters it out for not being confident enough.

This re-frames everything. The species-probe "failure" we spent two experiments studying wasn't a failure of the embedder. It was a failure of the threshold — set conservatively, set well before we had data, and never recalibrated.

---

## What this means for next steps

We won't deploy any embedder change off this experiment. The recommendation (switch to MiniLM × verbose) is small enough to be within measurement noise on a 60-query corpus, and verbose hasn't been validated against the rest of the pipeline (the reranker, the LLM that consumes the grounded values).

**The natural next experiment** is a single-cell threshold sweep on the current production stack — MiniLM, current format — to characterise the trade-off curve. The question to ask is: if we lower the threshold from 0.62 to, say, 0.55, how many more species-probe queries get answered correctly, and at what cost in false positives?

If that experiment yields a defensible operating point, the production change is "lower the threshold", not "switch the embedder". Much smaller change, much higher confidence.

**Beyond that**, the natural exp 2.3 would be domain fine-tuning — training an embedder specifically on food taxonomy relationships (turkey-is-a-poultry, lamb-is-a-meat). The taxonomy data is already in our knowledge base in structured form. This is a larger investment but is the cleanest way to solve the species-probe problem at its root rather than working around it with thresholds.

---

## The recommendation, in one line

**Keep MiniLM in production for now. The next investigation isn't a different embedder — it's a different threshold.**

---

## Why this experiment was worth running

Two experiments, one answer: the bottleneck wasn't where we thought it was.

We came in believing the embedder was failing on species queries. We leave knowing the embedder is fine — the gate is too tight. That changes what we work on next, how we measure success, and what we tell users about why the system says "I don't know" when it does.

The investigation also produced two artefacts that outlive the experiments: a 60-query ground-truth benchmark we can re-run against any future change, and a methodology for calibrating thresholds against asymmetric costs (safety matters more than coverage). Both will be reused.
