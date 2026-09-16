# Testing & Verifiability

## Contents
- The decisive question
- Does CI measure this repository?
- What the tests actually assert
- Mutation: asking the decisive question directly
- Coverage is a map of intent
- Silent-success patterns in this axis
- What to measure

## The decisive question

**What would have to break for a test to notice?**

Not "is there a test suite". Not "what is the coverage number". The question is whether the suite would fail if the system's important behaviour changed — and for a system you are about to build on, that is the question that determines whether you can refactor at all.

## Does CI measure this repository?

Check this before anything else, because a wrong answer here invalidates every other conclusion in the axis.

The failure shape is specific and common in forks: the README carries status badges, the badges are green, and the badge URLs point at the **upstream** repository. Nothing in the fork is tested; the badge reports someone else's build. `probe.sh` collects both halves — `ci-config` for what exists, `ci-badges` for what is claimed — and the finding lives in the gap between them.

```sh
# what CI exists here
find . -maxdepth 3 \( -path './.github/workflows/*' -o -name .gitlab-ci.yml -o -path './.circleci/*' -o -name Jenkinsfile \) -print
# not `ls … 2>/dev/null`: on a directory it cannot list, ls reports every name absent
# what the README claims — read the URLs, not the images
grep -ohE '!\[[^]]*\]\(https://[^)]*(badge|shield|workflow|actions)[^)]*\)' *.md
```

Three separate questions, each with its own answer:

1. **Does CI exist for this repo?** Files present, or not.
2. **Does it run?** A workflow file that no event triggers is decoration.
3. **Does failure block anything?** A required status check on protected branches, or a job that reports and is ignored. A suite nobody is obliged to keep green goes red and stays red.

The third is where most projects actually fail, and it is invisible from the repository alone — it lives in branch protection settings. If you cannot see them, say so and mark the finding `Unverified`.

## What the tests actually assert

Read a sample of tests, not just their names. Look for the shapes that pass regardless:

```
assert(true)                         a placeholder nobody removed
assertNotNull(result)                passes for almost any bug
mock everything, assert the mock     tests the mock, not the system
snapshot with no review              records current behaviour, including current bugs
no assertion at all                  passes unless the code throws
```

A test that cannot fail is worse than a missing test, because it occupies the slot where a real one would go and reports success while doing it. That is the silent-success class applied to the safety net itself.

Also note what has **no** test: the paths through which data enters the system, the authorization primitive, and anything handling money, identity, or clinical fact. Absence there is a finding regardless of the aggregate number.

## Mutation: asking the decisive question directly

Reading tests tells you what they appear to check. Breaking the code tells you what they do check. The decisive question — *what would have to break for a test to notice?* — has a direct experiment: break it, run the suite, and see.

In an audit, do it by hand and keep it small. Pick three to five behaviours the project cannot afford to lose — the authorization check, the write path, the thing the README says is tested — and for each, copy the tree, delete or invert that one behaviour, and run the suite. Record each as **killed** (the suite went red) or **survived** (it stayed green).

```
mutation (illustrative)                     result
delete the ACL check in PatientController   survived — 412 passed
return [] from the search service           killed — 3 failed
skip the audit-log write                    survived — 412 passed
```

A survivor is a Confirmed finding with its own reproduction, and it is the strongest evidence this axis produces: a behaviour the project believes is protected and is not. It also settles the claim no badge or coverage number can — a suite at 90% line coverage that lets the ACL check be deleted does not test authorization.

Where a mutation tool is already configured — Stryker, PIT, mutmut, Infection, cargo-mutants — read its last report. Do not install one to produce a score: a full run takes hours on a large codebase, and a mutation score has the same problem as a coverage number. Five hand mutations aimed at what matters answer the question; five thousand aimed at everything bury it.

Two cautions. Run the unmutated suite first and record its result, so a pre-existing failure is not counted as a kill. And make sure the suite actually exercises the copy you mutated — a test runner pointed at an installed package, a cached build, or the original tree will report every mutation as survived.

**Mutation measures the suite against its own stand-ins.** Where tests replace an external tool with a stub, a mock or a fixture, they pin the code to the author's belief about that tool, and every mutant is judged against that belief. Defects live where the belief is wrong: a scanner run with no arguments that audits the wrong subject passes a stub that echoes a report. For each wrapped external tool, one real run against a target whose correct answer is known beforehand is part of operating the system, and no mutation score substitutes for it.

## Coverage is a map of intent

Where a coverage tool is configured, read the report as a map of what the authors cared about rather than as a score. A number on its own is nearly meaningless — 80% coverage concentrated in getters and absent from the payment path is worse than 40% concentrated in the payment path.

Where no coverage tooling exists, do not install one and generate a number: that is new work, it will take longer than it looks, and the number will not survive scrutiny. Report the tooling gap instead, and count test files against source files as a crude ratio with the caveat attached.

## Silent-success patterns in this axis

| Pattern | How it shows up |
|---|---|
| Unchecked Output | the suite runs, reports pass, and asserts nothing meaningful |
| Missing Expected Metrics | a CI job silently stops triggering; nobody notices the absence |
| Success Codes on Failed Work | a test runner exits 0 when zero tests were collected |

The last one is worth a direct probe, because it is easy to check and catches a genuinely dangerous configuration: run the suite with a filter that matches nothing and look at the exit code. A runner that exits 0 on zero collected tests will report success after a refactor silently orphans the entire suite.

## What to measure

- Whether CI configuration exists in *this* repository.
- Whether badge URLs point here or upstream.
- Whether a failing run blocks a merge.
- Test count against source count, with the caveat stated.
- A read sample of tests, looking for assertions that cannot fail.
- Three to five hand mutations of load-bearing behaviour, each recorded as killed or survived.
- Exit code of the runner when zero tests are collected.
