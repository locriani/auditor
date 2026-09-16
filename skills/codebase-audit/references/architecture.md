# Architecture & Integration Surface

## Contents
- The decisive question
- Mapping verbs per resource
- Where the seams are
- What the prune left behind
- Behavioral analysis, and its absence
- Silent-success patterns in this axis
- What to measure

## The decisive question

**What is the read/write asymmetry, per resource, per verb?**

An API that documents thirty resources may accept writes on three of them. That fact is invisible in prose, invisible in the resource list, invisible in the client library, and absolutely binding on anything you plan to ingest. It becomes visible the moment you enumerate verbs, and not before.

Enumerate them. Do not sample.

## Mapping verbs per resource

Find the route table and count. Most frameworks declare routes in one place, and the declaration is greppable:

```sh
# a flat "VERB /path" => handler map
grep -ohE '"(GET|POST|PUT|PATCH|DELETE) /[A-Za-z0-9_/:.-]*"' <route-file> \
  | tr -d '"' | awk '{print $1}' | sort | uniq -c | sort -rn
```

Then build the table that matters — resource down the side, verb across the top — and look at the shape rather than the totals. What you are looking for:

- Resources that are read-only. These cannot be your ingest path, whatever the docs imply.
- Verbs absent everywhere. No `DELETE` anywhere in an API is a deliberate design stance with consequences for retention and correction.
- Resources writable by one route and readable by another with different authorization.

*Worked example.* An OpenEMR FHIR route map holds 71 route keys: 65 `GET` and 6 writes, covering only Patient, Organization, and Practitioner (`apis/routes/_rest_routes_fhir_r4_us_core_3_1_0.inc.php:546,553,560,569,677,684`). No `DELETE` or `PATCH` exists anywhere in the map. The consequence is concrete and was not discoverable any other way: loading clinical content through this API produces patients with empty charts, so ingest has to use a different path entirely.

## Where the seams are

A seam is a place you can insert behaviour without editing what surrounds it. Find them, because they determine whether integration is extension or surgery:

- Interfaces with more than one implementation — someone already anticipated variation there.
- Plugin, module, or hook registries.
- Service and repository layers between the entry point and storage.
- Event dispatch.

An existing pluggable interface is worth more than the same functionality hard-coded, because it means your addition is a new implementation rather than a patch. Say so explicitly when you find one — it converts an estimate from *construction* to *extension*, and that is exactly the kind of thing an audit is for.

## What the prune left behind

Where the tree is a fork or a subset, the residue of what was removed is reportable:

- Configuration for deleted subsystems.
- Submodule stanzas that are malformed or orphaned.
- Documentation describing components that are gone.
- Build steps referencing deleted paths.

None of it breaks anything today. All of it misleads the next reader, which is the cost you are pricing.

## Behavioral analysis, and its absence

Version-control history is evidence almost nobody reads. Where history exists, it answers questions static reading cannot:

```sh
git log --format=format: --name-only | grep -v '^$' \
  | sort | uniq -c | sort -rn | head -25       # change hotspots
git shortlog -sne HEAD                          # author concentration
```

Files that change constantly are where the design is wrong or the requirements are unstable; either way they are where your work will hurt. Files with one author are knowledge held by one person.

**Where history was squashed, the technique returns nothing — and that emptiness is the finding.** Report it as one: no bisect, no blame, no provenance, and no way to see what was removed on the way in. Distinguish it clearly from "the technique found no hotspots", which is a different result.

## Silent-success patterns in this axis

| Pattern | How it shows up |
|---|---|
| Empty-Result Ambiguity | an unsupported verb returns an empty success rather than 405 |
| Unchecked Output | a write is accepted, persists nothing, and returns 200 |
| Default Values Masking Loss | an unmapped field is dropped silently on ingest |

The third is worth a dedicated probe, because it is how data quietly disappears at a boundary: write a record with every field populated, read it back, and diff. Fields that vanish in the round trip are being dropped by a mapping layer that reports success.

## What to measure

- The full verb-by-resource table, counted, not sampled.
- Which resources are read-only and what that forbids.
- Seams available for extension, named.
- Residue of removed components.
- Hotspots and author concentration — or the explicit absence of history.
- Round-trip field fidelity across the ingest boundary.
