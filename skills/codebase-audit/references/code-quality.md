# Code Quality & Language Idiom

## Contents
- The decisive question
- Audit against the declared standard
- Per-language toolchain
- What to look at when nothing is declared
- Error handling is the idiom that matters
- Silent-success patterns in this axis
- What to measure

## The decisive question

**Does the code meet the standard it declares — and is one declared?**

The governing principle, and the thing that separates a useful finding from noise:

```
conformance(code, declared_standard)   → a finding
conformance(code, your_preference)     → noise
absence(declared_standard)             → a finding, and usually a bigger one
```

Running your favourite linter with default settings over someone else's codebase produces thousands of violations, tells you nothing, and destroys your credibility with the people who own it. Running *their* configured linter and reporting the delta tells you whether the project holds itself to the rule it published.

A project with no declared standard is the more interesting result. It means style is whatever the last committer preferred, review has no objective anchor, and any consistency you see is coincidence.

## Audit against the declared standard

1. Find the declaration. `probe.sh` lists the usual files in `lint-config`: `.editorconfig`, `.eslintrc*`, `phpcs.xml`, `psalm.xml`, `phpstan.neon`, `ruff.toml`, `.golangci.yml`, `.rubocop.yml`, and friends.
2. Check whether it is *enforced* or merely present. A linter config with no CI job and no pre-commit hook is an aspiration. That gap is itself the finding.
3. Run it as configured. Report the delta, not the absolute count.
4. Check whether the config has been weakened over time — rules disabled, files excluded, severities lowered. A shrinking standard is a trend worth naming.

Step 2 matters more than step 3. "The project declares a standard and does not enforce it" is a stronger finding than any particular violation count.

## Per-language toolchain

Run what the project declares. Where it declares nothing and you need a baseline, these are the conventional choices:

| Language | Syntax | Style | Types | Security |
|---|---|---|---|---|
| PHP | `php -l` | PHP_CodeSniffer, PHP-CS-Fixer | PHPStan, Psalm | `composer audit` |
| JavaScript / TypeScript | `node --check`, `tsc --noEmit` | ESLint, Prettier | `tsc` strict | `npm audit`, eslint-plugin-security |
| Python | `python -m compileall` | Ruff, flake8 | mypy, pyright | `bandit`, `pip-audit` |
| Go | `go vet` | `gofmt -l`, golangci-lint | built in | `govulncheck` |
| Rust | `cargo check` | `cargo fmt --check`, clippy | built in | `cargo audit` |
| Ruby | `ruby -c` | RuboCop | Sorbet, RBS | `bundle audit` |
| Shell | `bash -n` | shellcheck | — | shellcheck |

Syntax checks are cheap and worth running everywhere: they are fast, have no configuration argument attached, and a syntax error in a shipped file is unambiguous.

## What to look at when nothing is declared

Pick measurements that do not depend on taste:

- **Size outliers.** The longest files and functions. A 3,000-line file is a fact, not an opinion.
- **Duplication.** Copy-pasted blocks that have since diverged are latent bugs.
- **Dead code.** Unreferenced files and functions, especially after a prune.
- **Generated versus authored.** Vendored or generated code should be excluded from every count; including it makes every metric meaningless.
- **Comment accuracy.** Comments that describe behaviour the code no longer has. `@todo` and `@deprecated` markers on live paths are worth quoting directly.

## Error handling is the idiom that matters

Of all the per-language style questions, this is the one with audit consequences, because it is where the silent-success class is manufactured:

```
catch (…) { }                     swallowed, no record at all
catch (…) { log.debug(e); }       recorded where nobody looks
except: pass                      same, in Python
if err != nil { }                 checked and discarded, in Go
.catch(() => null)                a rejected promise becomes a null value
```

`probe.sh` greps for the empty-catch shape in `swallowed-exceptions`. Treat its output as candidates, not findings — read each one, because a deliberately empty catch with a comment explaining why is fine, and an identical one without is a defect. The distinction is the comment, and that is a judgment the grep cannot make.

## Silent-success patterns in this axis

| Pattern | How it shows up |
|---|---|
| Swallowed Exceptions | the dominant pattern in this axis, by a wide margin |
| Empty-Result Ambiguity | a function returns `null` for both "not found" and "lookup failed" |
| Default Values Masking Loss | a parse failure yields a zero value that flows onward as data |

## What to measure

- Whether a standard is declared, and whether anything enforces it.
- The delta against the project's own configuration.
- Syntax cleanliness per language.
- Count of empty or debug-only catch blocks, read individually.
- Size outliers and dead code, excluding vendored trees.
