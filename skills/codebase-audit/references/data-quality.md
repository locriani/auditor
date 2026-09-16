# Data Quality

## Contents
- The decisive question
- Null is three different facts
- Paired-write divergence
- Encoding, end to end
- Distributions, not counts
- Synthetic data understates everything
- Silent-success patterns in this axis
- What to measure

## The decisive question

**Is a field absent because there is none, or because it was never captured?**

These are opposite facts stored identically. In a clinical system, "no known allergies" and "nobody asked about allergies" are a safety distinction. In a financial one, "no chargebacks" and "chargeback data not ingested" are opposite conclusions from the same `NULL`.

Anything built on top will have to answer this question at query time. If the storage cannot distinguish the two, that limitation propagates into every downstream feature, and it must be stated as a constraint rather than discovered later by someone relying on it.

## Null is three different facts

```
NULL  =  known-absent  ∨  never-captured  ∨  capture-failed
```

Establish which ones the schema can represent. Usually the answer is "none of them, they are all NULL", and the follow-up is whether any other column disambiguates — a status field, a timestamp on the capture event, a sentinel row. Often something does and is simply undocumented.

Where nothing distinguishes them, say so plainly and name what it forbids: any downstream claim of the form "the patient has no X" is unsupportable, and the honest rendering is "no X recorded".

## Paired-write divergence

Wherever writing one row obliges writing another, count both sides. Divergence means a write sequence was interrupted between the two, and the system did not notice.

```sql
SELECT (SELECT COUNT(*) FROM documents)     AS documents,
       (SELECT COUNT(*) FROM audit_master)  AS audit_rows;
```

Equal counts are a *negative result worth reporting* — it means the pairing holds under the load the system has seen. Unequal counts are a finding, and the interesting part is which side is orphaned: a payload with no record of its arrival is different from a record pointing at a payload that does not exist.

*Worked example.* 98 `documents` rows against 97 `audit_master` rows: a bulk import hit a per-request CPU limit after writing the document and before writing the audit row. One document belongs to no patient, no error surfaced anywhere, and the two tables disagree. Nothing in the system would ever report this; it is visible only by counting both sides.

This is the single highest-yield probe in this axis. Find every paired write and count all of them.

## Encoding, end to end

Test with data that breaks naive pipelines, and test it through the *whole* path — ingest, storage, retrieval, render. Corruption at any single hop is invisible if you only inspect the endpoints.

Use diacritics, non-Latin scripts, emoji, right-to-left text, and names with apostrophes. Apostrophes earn their place twice: they break naive quoting in shell and SQL as well as display.

```sql
SELECT id, name FROM people WHERE name <> CONVERT(CONVERT(name USING BINARY) USING utf8mb4);
```

Check the declared charset at every layer — connection, database, table, column — since a mismatch at one hop mangles silently while every individual layer reports itself correctly configured. Intact encoding is a negative result, and worth stating as one.

## Distributions, not counts

Row counts tell you the system was used. Distributions tell you whether the data is fit for purpose.

- **Per-entity depth.** Minimum, median, maximum records per parent. The minimum finds empty parents; the maximum sets the worst case for retrieval.
- **Relative sparsity.** Which field types are rare relative to others. A field that is both rare and high-stakes is where downstream work will fail, and it is the eval case that matters most.
- **Date sanity.** Future dates, epoch-zero dates, ordering violations.
- **Duplicates.** By natural key, not by primary key.
- **Free text where structure was expected.** A coded field carrying prose means the coding is unreliable for querying.

*Worked example.* 112 allergy rows against 8,037 lab results across 97 patients. The sparsest field is also the highest-stakes one — "is this patient allergic to X" is exactly the question a clinical assistant gets asked, and exactly where the data is thinnest. That combination is the finding, and neither number alone would have produced it.

## Synthetic data understates everything

If the data is generated, say so prominently and treat every clean result as provisional.

Synthetic generators produce internally consistent records with uniform structure and no history. They do not produce the things that actually break systems: duplicate people with slightly different names, records corrected after the fact, legacy rows from three schema versions ago, free text where a code belongs, entries made by someone in a hurry.

So a clean data-quality result on synthetic data is evidence about the *generator*, not about the system. State this in the appendix — it is a boundary, and claiming coverage you do not have is the failure mode this axis is most prone to.

## Silent-success patterns in this axis

| Pattern | How it shows up |
|---|---|
| Default Values Masking Loss | a failed parse becomes `0` or `""` and flows onward as data |
| Unchecked Output | the importer reports success; nothing counts what landed |
| Empty-Result Ambiguity | a query returns nothing, and nothing distinguishes empty from broken |

## What to measure

- Whether the schema can distinguish known-absent from never-captured.
- Every paired write, counted on both sides.
- An encoding round trip through the full path, with adversarial strings.
- Per-entity depth: min, median, max.
- Relative sparsity, with the high-stakes fields named.
- Whether the data is synthetic, stated prominently.
