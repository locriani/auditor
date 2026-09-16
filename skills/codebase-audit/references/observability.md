# Observability & Operability

## Contents
- The decisive question
- Health is three different questions
- Can you answer a question you did not anticipate?
- Failure modes and what announces them
- Operability
- Silent-success patterns in this axis
- What to measure

## The decisive question

**When it fails at 3am, what tells you, and how fast?**

The honest answer for most inherited systems is "a user does, the next morning". Establishing that plainly is worth more than an inventory of logging calls, because it sets the baseline that anything you add has to beat.

## Health is three different questions

Systems conflate them, and the conflation is the finding:

```
liveness   is the process alive?          restart fixes it
readiness  can it serve traffic now?      dependencies are up, migrations done
health     is it behaving correctly?      the one that actually matters
```

A liveness endpoint returning 200 from a process whose database is unreachable is technically correct and operationally useless. Check what each endpoint actually verifies — most return a literal constant. That is fine for liveness and a lie for readiness.

Where a pluggable health interface already exists, say so explicitly: adding a check becomes a new implementation rather than new infrastructure, which changes the estimate for anything you build. `probe.sh` collects candidates in `health-endpoints`.

## Can you answer a question you did not anticipate?

This is the test that separates logging from observability.

```
logging        you recorded what you expected to need
observability  you can ask a new question of existing data
```

Concretely: can you take one user-visible failure and trace it to a cause using only what the system already emits? Try it. Pick a request, follow it through the logs, and see how far you get.

What determines the answer:

- **Correlation.** Is there a request or trace ID that appears in every line belonging to one operation? Without it, concurrent requests interleave into noise and the trail ends at the first async boundary.
- **Structure.** Machine-parseable records can be queried. Free-text lines can be grepped, which is a different and much weaker capability.
- **Level discipline.** If everything is INFO, level carries no information and cannot be used to filter.
- **Retention.** Data that ages out before anyone investigates is not evidence.

## Failure modes and what announces them

Enumerate the ways the system fails, and for each one name the signal:

| Failure | Signal | Time to detection |
|---|---|---|
| process crash | restart, alert | seconds |
| dependency down | ? | ? |
| partial batch completion | ? | ? |
| silent data divergence | ? | ? |

Fill the table honestly. The rows with `?` in the signal column are your findings, and the pattern is usually stark: crashes are well covered, and everything quiet is not covered at all. That asymmetry is exactly what you would expect from a system instrumented by reacting to incidents, and naming it is more useful than listing individual gaps.

**Absence alerts are the missing instrument.** Almost every system alerts on error rate; almost none alert on *expected signal not arriving*. A nightly job that stops running produces no errors — it produces nothing, and nothing is not monitored. Where downstream work depends on periodic or async behaviour, the absence of an absence alert is a finding.

## Operability

- **Configuration.** Environment, files, database, or all three. Multiple sources with unclear precedence is its own defect.
- **Rollback.** Can you go back? Do migrations run forward only?
- **Startup dependencies.** What must be up first, and what happens if it is not — clean fail, or a partially initialised process serving errors?
- **Runbooks.** Whether documented procedures exist, and whether they match the system as it is now.

## Silent-success patterns in this axis

| Pattern | How it shows up |
|---|---|
| Missing Expected Metrics | the signal that should be there is not; nothing watches for absence |
| Swallowed Exceptions | the error exists and was never emitted |
| Success Codes on Failed Work | a health endpoint returns 200 from a broken process |

## What to measure

- What each health endpoint actually verifies, read from its implementation.
- Whether a correlation ID survives an async boundary.
- Whether logs are structured or free text.
- The failure/signal table, with the gaps left visible.
- Whether anything alerts on absence rather than on errors.
- Retention window against the time it takes anyone to investigate.
