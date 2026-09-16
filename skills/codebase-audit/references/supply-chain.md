# Supply Chain & Dependencies

## Contents
- The decisive question
- Does the build produce your code?
- Provenance of the tree itself
- Dependency posture
- Silent-success patterns in this axis
- What to measure

## The decisive question

**Does the build produce *your* code, from sources you can name?**

This axis exists separately from Security because it is a different discipline with a different failure mode. A security bug is code that does the wrong thing. A supply-chain failure is *the wrong code*, doing exactly what it was written to do, in a build that succeeded.

## Does the build produce your code?

Read every build definition for a network fetch. `probe.sh` isolates these in `dockerfile-fetches` precisely because they are the ones that matter:

```
git clone <upstream>    the build ignores the tree you audited
ADD https://…           an unpinned artifact, whatever it is today
curl … | sh             remote code, executed, unverified
FROM image:latest       a different base image tomorrow
```

A Dockerfile that clones upstream inside a fork is the sharpest version: the build is green, the image runs, the application works, and none of your changes are in it. Nothing anywhere reports a problem, because from the build's point of view there is not one.

**The probe that settles it is an identity assertion.** Stamp something into the artifact that could only have come from your tree, then assert it after the build:

```sh
# at build time
LABEL org.opencontainers.image.source="<your repo>"
LABEL org.opencontainers.image.revision="<your commit sha>"

# after the build — this is the check, and it belongs in CI
docker inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' <image>
```

Without an assertion like this, "we deployed the fork" is a belief, not a fact. Recommend it as the remediation; the finding is that nothing currently distinguishes the two outcomes.

## Provenance of the tree itself

Where did this code come from, and can you prove it?

- **Commit count.** A single squashed commit means there is no history to audit: no bisect, no blame, no way to see what was removed on the way in. That is a real loss, and worth stating as a finding even though nothing is broken.
- **Diff against upstream**, where the project is a fork. What was pruned, and does anything still reference it? Orphaned submodule stanzas and configuration for deleted subsystems are the residue.
- **Tags and releases.** Does a version in the manifest correspond to anything in history?
- **Author concentration.** One author across the entire tree tells you the bus factor and the review depth in one number.

## Dependency posture

`probe.sh` runs the ecosystem's own auditor where a manifest exists — `composer audit`, `npm audit`, `pip-audit`, `govulncheck`, `cargo audit` — each of which resolves against a live advisory database. Read the output rather than the exit code: several of these exit non-zero *because* they found something, which is a success of the tool and a finding for you.

Beyond CVEs, three things matter and none are in the audit output:

- **Pinning.** Does a rebuild today produce the same dependency set as last week? A lockfile committed is the answer; a lockfile gitignored is a finding.
- **Transitive depth and abandonment.** A direct dependency with no release in years is a maintenance liability even with no CVE against it.
- **Licence compatibility** with what you intend to do. Copyleft in a dependency of a product you plan to distribute is a legal constraint that arrives late and expensively.

## Silent-success patterns in this axis

| Pattern | How it shows up |
|---|---|
| Unchecked Output | the build succeeds; nothing verifies what is in the artifact |
| Default Values Masking Loss | a config migration comments out a key and the builder silently falls back |
| Best-Effort Writes Unverified | a volume declared wrongly is accepted and simply does not persist |

The second and third share a shape worth naming: **a configuration file that validates is not a configuration that does what you meant.** Schema validity and semantic correctness are different properties, and every IaC tool will tell you about the first while staying silent on the second. The probe is to inspect the *resolved plan*, not the source config — what the tool decided to do, rather than what you wrote.

## What to measure

- Every network fetch in every build definition, with `path:line`.
- Whether any post-build assertion distinguishes your code from upstream's.
- Commit count, author count, and whether history survives.
- Auditor output per ecosystem, read rather than exit-coded.
- Whether a lockfile is committed.
