# Security

## Contents
- The decisive question
- Locating the enforcement layer
- The second authorization system
- Defaults that are not defaults
- Secrets
- Silent-success patterns in this axis
- What to measure

## The decisive question

**At what layer is authorization enforced — UI, service, or data?**

Everything else in this axis is detail. This one answers whether anything you build can reach the data directly, and it decides an integration architecture in a single fact:

```
enforced_at(UI)      →  any direct query bypasses all access control
enforced_at(service) →  reachable only through the service layer
enforced_at(data)    →  row/column policy travels with the data
```

If enforcement is UI-layer only, then a background job, a report generator, an agent tool, or anything else holding a database handle has the privileges of the connection, not of the user. That is not a bug to file — it is a constraint on everything downstream, and it must be stated as one.

Answer it by following a single read from the entry point to the query. Do not accept the presence of a check as proof of a layer; find where the check sits relative to the query, and look for a path to the same data that does not pass it.

## Locating the enforcement layer

1. Find the authorization primitive — the function everything calls. Grep for the obvious names (`can`, `authorize`, `checkAccess`, `acl`, `gate`, `policy`, `permit`).
2. Read it. Note every early return, especially ones that return *allow*.
3. Find one clinical/business read path and trace it end to end.
4. Then find a second path to the same table — a CLI, a cron job, an export, a report, a module — and check whether it passes the same primitive.

Step 4 is where the finding usually is. Systems grow side doors.

**Early returns are the whole ballgame.** An authorization function that short-circuits to `true` has an unwritten rule nobody documented. Two shapes recur:

```
superuser short-circuit   if user is admin → allow, without consulting the policy
unconfigured-means-open   if no policy is defined for this object → allow
```

The second is the more dangerous of the pair, because it converts *"nobody got around to configuring this"* into *"everyone can read it"*, and it fails open at exactly the moment a new feature is added. Grade it on likelihood honestly: if the shipped configuration leaves objects unconfigured, likelihood is Default.

*Worked example (OpenEMR, php-gacl).* `AclMain::aclCheckCore` recurses into an `admin|super` check and returns `true` before querying the ACL at all (`src/Common/Acl/AclMain.php:174-176`); `aclCheckAcoSpec` returns `true` when the ACO spec is empty (`:337-339`), and that flows through `aclCheckForm` and `aclCheckIssue` (`:370-372`). Both are real, both are one line, and neither is visible unless you read the primitive rather than its call sites.

## The second authorization system

Ask whether the API enforces the same model as the session.

An OAuth2 scope check and a session ACL are frequently *different systems over one dataset*, written years apart, agreeing by coincidence. Where they disagree, the more permissive one is the system's real policy. Check:

- Does a token scope map onto a role, or is it a parallel vocabulary?
- Can a token reach a resource the equivalent session user cannot?
- Does any module ship its own check instead of calling the shared primitive?

*Worked example.* `AclMain::zhAclCheck` (`AclMain.php:252`) bypasses php-gacl entirely and hand-rolls SQL across `module_acl_*` and `gacl_*`. Two authorization systems, one dataset.

## Defaults that are not defaults

Credentials shipped in a repository are only interesting once you establish where they apply. Separate them:

- **Dev-only, never deployed** — record as Info, and say why it is Info.
- **Present in the production compose or image** — this is the finding.

The grading question is whether deploying the documented way reproduces the credential. If yes, likelihood is Default and impact is whatever the account can reach.

## Secrets

`probe.sh` greps for assigned literals rather than bare keywords, because a name alone is a false positive. For each hit, establish three things before grading: is it live, what does it reach, and is it in git history as well as the working tree. A rotated secret still in history is a finding with a different remediation, not a non-finding.

## Silent-success patterns in this axis

| Pattern | How it shows up |
|---|---|
| Success Codes on Failed Work | authorization failure returns an empty result set and HTTP 200 |
| Empty-Result Ambiguity | "no records" and "not permitted" are the same response |
| Default Values Masking Loss | an unset policy renders as permissive rather than as an error |

The middle one deserves a probe of its own: request a record you should not be allowed to see, and compare the response to a record that does not exist. If they are byte-identical, the system cannot distinguish denial from absence — which is defensible as a design choice and indefensible if unintentional. Ask which it was.

## What to measure

- The path from entry point to query, for one read, written down.
- Every early return in the authorization primitive, with line numbers.
- Whether a second path to the same data exists that skips the primitive.
- Whether API and session enforcement are the same code.
- Which credentials survive a documented deployment.
