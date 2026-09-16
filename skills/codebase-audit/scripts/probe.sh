#!/usr/bin/env bash
#
# probe.sh — one-pass evidence collection for a codebase audit.
#
# Detects the stack rather than assuming it, runs every applicable probe once,
# and writes an evidence bundle plus manifest.tsv. Prints the bundle path.
#
# The manifest keeps five outcomes distinct, which is the whole point:
#   ok      ran, found something          empty  ran clean, found nothing
#   n/a     does not apply to this stack  error  could not run — you know NOTHING here
#   output  exited nonzero AND produced output — READ IT. Vulnerability scanners
#           signal findings this way; discarding it throws away the best evidence.
#
# "empty" and "error" are meant never to be the same value. Collapsing them is
# Empty-Result Ambiguity — the first defect class this tool exists to hunt, and
# one this script committed in v1.0.0 by suffixing 17 probes with `|| true`.
# What it still cannot promise is listed under "What probe.sh does not
# guarantee" in SKILL.md.
#
# Exit codes: 0 the run completed (findings are not failures)
#             2 usage error, or the target does not exist
#
# Written for bash 3.2 (macOS system bash) — no associative arrays, no mapfile.

set -eu

TARGET=""; BUNDLE=""; HOST_CONTAINERS=0; PTIMEOUT="120"   # seconds per probe; --timeout 0 disables

# The synopsis lives here, not in the header. v1.0.0–1.2.x printed it with
# `sed -n '3,6p' "$0"`, which went wrong the first time the header moved.
usage() {
  cat <<'USAGE'
probe.sh <target-dir> [-o <bundle-dir>] [--host-containers] [--timeout N]

  -o <dir>            new or empty directory, or a bundle probe.sh created before
  --host-containers   also inspect running containers on this host (off by default)
  --timeout N         whole seconds per probe, default 120, 0 disables; needs a
                      timeout or gtimeout binary, and env.txt says whether one ran
USAGE
  exit 2
}

while [ $# -gt 0 ]; do
  case "$1" in
    -o) [ $# -ge 2 ] || usage; BUNDLE="$2"; shift 2 ;;
    --host-containers) HOST_CONTAINERS=1; shift ;;
    --timeout) [ $# -ge 2 ] || usage; PTIMEOUT="$2"; shift 2 ;;
    -h|--help) usage ;;
    --) shift ;;
    -*) echo "unknown option: $1" >&2; usage ;;
    *)  [ -z "$TARGET" ] || { echo "target given twice" >&2; usage; }
        TARGET="$1"; shift ;;
  esac
done

[ -n "$TARGET" ] || usage
# v1.2.0 interpolated the timeout into an `eval`d string, so `--timeout '1; cmd'`
# ran cmd once per probe. The value is no longer eval'd, and is still validated
# here, before any file is written.
case "$PTIMEOUT" in
  ''|*[!0-9]*) echo "invalid --timeout: '$PTIMEOUT' (whole seconds, or 0 to disable)" >&2; exit 2 ;;
esac
[ -d "$TARGET" ] || { echo "not a directory: $TARGET" >&2; exit 2; }
TARGET=$(cd "$TARGET" && pwd)

if [ -z "$BUNDLE" ]; then
  BUNDLE="${TMPDIR:-/tmp}/codebase-audit-$(basename "$TARGET")-$(date +%Y%m%d-%H%M%S)"
fi
# A reused bundle must not mix runs: stale evidence from a previous target reads
# as current fact and nothing in the manifest would say otherwise. But only a
# directory this script created may be cleared. v1.2.0 ran `rm -rf "$BUNDLE/out"`
# unconditionally, so `-o` pointed at a project with a build `out/` directory
# destroyed it silently. The marker file is the proof of ownership.
MARKER=".codebase-audit-bundle"
if [ -e "$BUNDLE" ] && [ ! -d "$BUNDLE" ]; then
  echo "refusing: bundle path exists and is not a directory: $BUNDLE" >&2; exit 2
fi
if [ -d "$BUNDLE" ] && [ -n "$(ls -A "$BUNDLE" 2>/dev/null)" ]; then
  if [ ! -f "$BUNDLE/$MARKER" ]; then
    echo "refusing: $BUNDLE is not empty and was not created by probe.sh" >&2
    echo "          (no $MARKER marker). Nothing was modified. Choose an empty" >&2
    echo "          or new directory for -o." >&2
    exit 2
  fi
  rm -rf "$BUNDLE/out"
fi
mkdir -p "$BUNDLE/out"
printf 'created by codebase-audit probe.sh; safe for probe.sh to clear on reuse\n' > "$BUNDLE/$MARKER"
MANIFEST="$BUNDLE/manifest.tsv"
printf 'probe\taxis\tstatus\texit\tbytes\tlines\tstderr\tfile\tnote\n' > "$MANIFEST"

# A timeout guard, where one is available. Two probes talk to a daemon and one
# to the network; without this a hung daemon hangs the whole collection. Stock
# macOS has neither binary, and env.txt records which case applied.
TIMEOUT_BIN=""
if [ "$PTIMEOUT" != "0" ]; then
  if command -v timeout >/dev/null 2>&1; then TIMEOUT_BIN="timeout"
  elif command -v gtimeout >/dev/null 2>&1; then TIMEOUT_BIN="gtimeout"
  fi
fi
TIMEOUT_PREFIX=""; [ -z "$TIMEOUT_BIN" ] || TIMEOUT_PREFIX="$TIMEOUT_BIN $PTIMEOUT"

# probe <name> <axis> <cmd> [ok_exits] [cap] [failed_if] [empty_note]
#
# ok_exits   space-separated exit codes that mean "ran correctly" (default "0").
#            grep exits 1 for "no match" and xargs 123 when a checker it ran
#            reported something — RESULTS, not failures.
# cap        lines kept in out/<name>.txt. More than that is flagged TRUNCATED and
#            the whole output is kept in out/<name>.full.txt. Commands must not
#            cap themselves with `| head`: that pins the pipeline's exit status
#            to head's, which is how v1.2.0's `exit` column came to report 0 for
#            24 of 39 probes whatever the producer did.
# failed_if  an extended regex that, found in the output, means the tool reported
#            it could not run. For tools whose "found something" exit is also
#            their "could not start" exit, only the content can separate the two.
#            v1.2.0 filed `npm audit` failing with ENOLOCK as `ok`.
# empty_note what an `empty` row says, where "ran clean" would overclaim.
#
# Each command runs in its own bash with pipefail ON, so any stage failing is the
# probe failing. (pipefail was off in v1.2.x to stop `head` SIGPIPE reading as
# exit 141; with the cap moved here there is no `head` to cause it.) The command
# is passed to that bash as one argument, never eval'd, and the timeout binary
# wraps the whole of it — v1.2.0's `timeout 120 for c in …` was a syntax error.
probe() {
  _name="$1"; _axis="$2"; _cmd="$3"; _ok="${4:-0}"; _cap="${5:-}"; _failpat="${6:-}"; _emptynote="${7:-}"
  _out="$BUNDLE/out/$_name.txt"; _full="$BUNDLE/out/$_name.full.txt"; _err="$BUNDLE/out/$_name.err"; _rc=0
  # shellcheck disable=SC2086  # TIMEOUT_PREFIX is a binary name and validated digits
  ( cd "$TARGET" && exec $TIMEOUT_PREFIX "$BASH" -o pipefail -c "$_cmd" ) >"$_full" 2>"$_err" || _rc=$?

  _total=$(wc -l < "$_full" | tr -d ' ')
  _truncated=0
  if [ -n "$_cap" ] && [ "$_total" -gt "$_cap" ]; then
    head -n "$_cap" "$_full" > "$_out"; _truncated=1
  else
    mv -f "$_full" "$_out"
  fi
  _bytes=$(wc -c < "$_out" | tr -d ' ')
  _lines=$(wc -l < "$_out" | tr -d ' ')
  if [ -s "$_err" ]; then _haserr="yes"; else _haserr="no"; rm -f "$_err"; fi

  _expected=0
  for _c in $_ok; do [ "$_rc" = "$_c" ] && _expected=1; done

  if [ -n "$TIMEOUT_BIN" ] && [ "$_rc" = "124" ]; then
    _status="error"
    _note="TIMED OUT after ${PTIMEOUT}s — the output file holds only what arrived before the kill"
  elif [ -n "$_failpat" ] && grep -qE "$_failpat" "$_out"; then
    _status="error"
    _note="exited $_rc; output says the tool did not run ($(grep -oE "$_failpat" "$_out" | head -1 | tr '\t' ' ' | cut -c1-80)) — out/$_name.txt holds its error, not results"
  elif [ "$_expected" -eq 1 ]; then
    if [ "$_bytes" -eq 0 ]; then
      _status="empty"; _note="${_emptynote:-ran clean, produced no output}"
    else
      _status="ok"; _note="see output file"
    fi
  elif [ "$_bytes" -gt 0 ]; then
    # A producer failed partway, or a scanner signalled findings with its exit.
    _status="output"
    _note="exited $_rc and produced output — read it, do not discard"
  else
    _status="error"
    _note=$(head -c 160 "$_err" 2>/dev/null | tr '\n\t' '  ' | sed 's/  */ /g')
    [ -n "$_note" ] || _note="exited $_rc with no stderr"
  fi

  if [ "$_truncated" -eq 1 ]; then
    _note="TRUNCATED: $_cap of $_total lines shown, all in out/$_name.full.txt. $_note"
  fi
  if [ "$_haserr" = "yes" ]; then
    _note="$_note [stderr present: out/$_name.err]"
  fi

  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$_name" "$_axis" "$_status" "$_rc" "$_bytes" "$_lines" "$_haserr" \
    "out/$_name.txt" "$_note" >> "$MANIFEST"
}

# skip <name> <axis> <reason> — an inapplicable probe, recorded explicitly.
# Silence here is indistinguishable from a probe that was never written.
skip() {
  printf '%s\t%s\tn/a\t-\t0\t0\tno\t-\t%s\n' "$1" "$2" "$3" >> "$MANIFEST"
}

has() { command -v "$1" >/dev/null 2>&1; }
exists() { [ -e "$TARGET/$1" ]; }

# A real prune, at any depth. v1.2.0 used `-not -path "./node_modules/*"`, which
# matches only at the root — nested vendor trees leaked into every count — and
# still walked .git, so git housekeeping mid-run filled the stderr column with
# noise. Every find using this must end its own expression with an action.
PRUNE='\( -name .git -o -name node_modules -o -name vendor \) -prune -o'
# grep -r ignores find's prune, so vendored and generated trees have to be excluded
# explicitly or they dominate every result set. Minified files are excluded by name:
# a single 400KB line of bundled JS matches almost any pattern and proves nothing.
GREP_EX='--exclude-dir=.git --exclude-dir=node_modules --exclude-dir=vendor --exclude-dir=dist --exclude-dir=build --exclude-dir=coverage --exclude-dir=.venv --exclude-dir=__pycache__ --exclude-dir=third_party --exclude-dir=jquery --exclude="*.min.js" --exclude="*.min.css" --exclude="*.map" --exclude="*-lock.json" --exclude="*.lock"'

# `ls -l | awk '{print $9}'` cut every path at its first space. stat prints the
# size and the whole name; the flag spelling differs between GNU and BSD.
if stat -c '%s' "$0" >/dev/null 2>&1; then STAT_SIZE="stat -c '%s %n'"; else STAT_SIZE="stat -f '%z %N'"; fi

# secret-scan reads only these. Named here so env.txt and the empty note can say
# so: an `empty` means "no assigned literal in THESE files", never "no secrets".
SECRET_GLOBS='*.y*ml *.env* *.json *.ini *.conf *.cfg *.toml *.xml *.properties *.tf *.tfvars *.sh *.php *.ts *.tsx *.js *.jsx *.mjs *.cjs *.vue *.py *.rb *.go *.java *.kt *.kts *.scala *.gradle *.cs *.rs *.swift *.c *.cc *.cpp *.h *.hpp *.md Dockerfile* Makefile'
# set -f: unquoted, `*.md` expands against the CALLER's directory — run from one
# holding CLAUDE.md, the scan silently read CLAUDE.md instead of every .md file.
SECRET_INC=""
set -f; for _g in $SECRET_GLOBS; do SECRET_INC="$SECRET_INC --include='$_g'"; done; set +f

{
  echo "target:     $TARGET"
  echo "collected:  $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  echo "host:       $(uname -srm)"
  echo "bash:       ${BASH_VERSION:-unknown}"
  echo "host-containers: $HOST_CONTAINERS"
  if [ -n "$TIMEOUT_BIN" ]; then
    echo "timeout:    ${PTIMEOUT}s per probe, enforced by $TIMEOUT_BIN"
  elif [ "$PTIMEOUT" = "0" ]; then
    echo "timeout:    none — disabled with --timeout 0"
  else
    echo "timeout:    NONE ENFORCED — ${PTIMEOUT}s requested, but neither timeout nor gtimeout is on PATH; probes ran unbounded"
  fi
  echo "secret-scan reads: $SECRET_GLOBS"
} > "$BUNDLE/env.txt"

# ---------------------------------------------------------------- provenance
# `[ -d .git ]` was wrong: a target inside a work tree with no .git of its own
# reported "not version controlled", which is a different claim entirely.
GITSCOPE=""
if has git && ( cd "$TARGET" && git rev-parse --is-inside-work-tree ) >/dev/null 2>&1; then
  GITROOT=$( cd "$TARGET" && git rev-parse --show-toplevel )
  if [ "$GITROOT" = "$TARGET" ]; then GITSCOPE="repo root"; else GITSCOPE="subdirectory of $GITROOT"; fi
  echo "git scope:  $GITSCOPE" >> "$BUNDLE/env.txt"
  probe git-remotes      supply-chain 'git remote -v'
  # -41 against a cap of 40: one line past the cap is how the probe knows more exists.
  probe git-log          supply-chain 'git log --oneline -41 -- .' 0 40
  probe git-commit-count supply-chain 'git rev-list --count HEAD -- .'
  probe git-authors      supply-chain 'git shortlog -sne HEAD -- .'
  probe git-status       supply-chain 'git status --short -- .'
  probe git-tracked      supply-chain 'git ls-files -- .' 0 40
  probe git-tags         supply-chain 'git tag --list' 0 40
  probe git-submodules   supply-chain 'test -f .gitmodules && cat .gitmodules' '0 1'
  probe git-churn        code-quality \
    'git log --format=format: --name-only -- . | grep -v "^$" | sort | uniq -c | sort -rn' '0 1' 25
else
  for p in git-remotes git-log git-commit-count git-authors git-status git-tracked git-tags git-submodules; do
    skip "$p" supply-chain "not inside a git work tree, or git not installed"
  done
  skip git-churn code-quality "no git history to mine"
fi

# ---------------------------------------------------------------- dependencies
DEPS=0
if exists composer.json; then DEPS=1
  probe composer-manifest supply-chain 'cat composer.json'
  if has composer; then probe composer-audit supply-chain 'composer audit --format=plain --no-interaction' '0 1 2'
  else skip composer-audit supply-chain "composer.json present but composer not on PATH"; fi
fi
if exists package.json; then DEPS=1
  probe npm-manifest supply-chain 'cat package.json'
  # npm audit exits 1 when it FINDS vulnerabilities. That is the finding.
  # It also exits 1 when it cannot audit at all (ENOLOCK: no lockfile), and
  # prints a JSON error object to stdout — so the content decides, not the exit.
  if has npm; then probe npm-audit supply-chain 'npm audit --json' '0 1' '' '"code"[[:space:]]*:[[:space:]]*"E[A-Z0-9]+"'
  else skip npm-audit supply-chain "package.json present but npm not on PATH"; fi
fi
if exists requirements.txt || exists pyproject.toml; then DEPS=1
  if has pip-audit; then probe pip-audit supply-chain 'pip-audit --progress-spinner off' '0 1'
  else skip pip-audit supply-chain "python manifest present but pip-audit not installed"; fi
fi
if exists go.mod; then DEPS=1
  if has govulncheck; then probe go-vulncheck supply-chain 'govulncheck ./...' '0 3'
  else skip go-vulncheck supply-chain "go.mod present but govulncheck not installed"; fi
fi
if exists Cargo.toml; then DEPS=1
  if has cargo; then probe cargo-audit supply-chain 'cargo audit' '0 1'
  else skip cargo-audit supply-chain "Cargo.toml present but cargo not on PATH"; fi
fi
if exists Gemfile; then DEPS=1
  if has bundle; then probe bundler-audit supply-chain 'bundle audit check --update' '0 1'
  else skip bundler-audit supply-chain "Gemfile present but bundler not on PATH"; fi
fi
[ "$DEPS" -eq 1 ] || skip dependency-audit supply-chain "no recognised package manifest at the target root"

# ---------------------------------------------------------------- build inputs
# find exits 1 only when it could not read something, so find probes accept 0 alone.
probe dockerfiles supply-chain \
  "find . $PRUNE -name 'Dockerfile*' -print" 0 20
probe dockerfile-fetches supply-chain \
  "grep -rHnE '(git clone|curl|wget|ADD https?://)' --include='Dockerfile*' $GREP_EX ." '0 1'
probe compose-files supply-chain \
  "find . $PRUNE \\( -name 'docker-compose*.y*ml' -o -name 'compose.y*ml' \\) -print" 0 20

# ---------------------------------------------------------------- runtime
# Opt-in only. A filename match inside the target is NOT consent to enumerate
# and exec into every container on the host — that is evidence about the machine,
# not about the tree, and v1.0.0 did it by default.
if [ "$HOST_CONTAINERS" -eq 1 ] && has docker; then
  probe docker-ps observability 'docker ps --format "{{.Names}}\t{{.Status}}\t{{.Image}}\t{{.Ports}}"'
  probe db-clients data-quality \
    'for c in $(docker ps --format "{{.Names}}"); do for b in mariadb mysql psql mongosh sqlite3 redis-cli; do if docker exec "$c" sh -c "command -v $b" >/dev/null 2>&1; then echo "$c: $b"; fi; done; done' '0 1'
else
  skip docker-ps  observability "host container inspection is opt-in; pass --host-containers"
  skip db-clients data-quality  "host container inspection is opt-in; pass --host-containers"
fi

# ---------------------------------------------------------------- secrets
probe secret-scan security \
  "grep -rInE '(password|passwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key)[[:space:]]*[:=][[:space:]]*\"?'\"'\"'?[A-Za-z0-9_./+=-]{6,}' $SECRET_INC $GREP_EX . | grep -viE '(example|sample|placeholder|changeme|your[_-]|xxx|csrf|jquery|function|typeof|prototype|[$][{]|[$][A-Z_]+)'" '0 1' 40 '' \
  "no assigned literal in the file types listed in env.txt — other files were not read; this is not evidence of no secrets"
probe env-files security "find . $PRUNE -name '.env*' -print" 0 20
probe published-ports security \
  "grep -rhnE '^[[:space:]]*-[[:space:]]*\"?[0-9]{2,5}:[0-9]{2,5}' --include='docker-compose*.y*ml' --include='compose*.y*ml' $GREP_EX ." '0 1' 40

# ---------------------------------------------------------------- surface
probe route-tables architecture \
  "grep -rlIE '(GET|POST|PUT|PATCH|DELETE)[[:space:]]+/' --include='*.php' --include='*.js' --include='*.ts' --include='*.py' --include='*.rb' --include='*.go' $GREP_EX . | grep -viE '(node_modules|vendor|test|spec)'" '0 1' 20
probe route-verbs architecture \
  "grep -rhoIE '\"(GET|POST|PUT|PATCH|DELETE) /[A-Za-z0-9_/:.-]*\"' --include='*.php' --include='*.inc.php' --include='*.js' --include='*.ts' $GREP_EX . | tr -d '\"' | awk '{print \$1}' | sort | uniq -c | sort -rn" '0 1' 20

# ---------------------------------------------------------------- declared standard
# find rather than `ls … 2>/dev/null`: on a target it cannot list, ls reports
# every name missing and exits 1, which v1.2.x filed as `empty`.
probe lint-config code-quality \
  "find . -maxdepth 1 \\( -name .editorconfig -o -name '.eslintrc*' -o -name 'eslint.config.*' -o -name '.prettierrc*' -o -name 'phpcs.xml*' -o -name '.php-cs-fixer*' -o -name 'psalm.xml*' -o -name 'phpstan.neon*' -o -name ruff.toml -o -name .flake8 -o -name setup.cfg -o -name tox.ini -o -name rustfmt.toml -o -name '.golangci.y*ml' -o -name .rubocop.yml \\) -print | sort"
probe lang-census code-quality \
  "find . $PRUNE -type f -name '*.*' -print | sed 's/.*\\.//' | sort | uniq -c | sort -rn" 0 20
if exists composer.json && has php; then
  probe php-syntax code-quality \
    "find . $PRUNE -name '*.php' -exec sh -c 'rc=0; for f; do php -l \"\$f\" 2>&1; case \$? in 0|255) ;; *) rc=1 ;; esac; done; exit \$rc' sh {} + | awk '!/^No syntax errors/'" 0 40
else
  skip php-syntax code-quality "no composer.json, or php not on PATH"
fi
# shellcheck absence is a DOWNGRADE, not a clean result — say which ran.
#
# Checkers run inside `find -exec sh -c`, which maps "the checker found something"
# (php -l 255, shellcheck 1, bash -n 2) to success and anything else to failure.
# xargs cannot do that: BSD xargs reports every nonzero child as 1, the same exit
# as find failing to read a directory, so a syntax error and an unreadable tree
# were indistinguishable. Exit 1 from these probes now means only the latter.
if has shellcheck; then
  probe shell-lint code-quality \
    "find . $PRUNE -name '*.sh' -exec sh -c 'shellcheck -f gcc \"\$@\"; [ \$? -le 1 ]' sh {} +" 0 60
else
  probe shell-syntax-only code-quality \
    "find . $PRUNE -name '*.sh' -exec sh -c 'rc=0; for f; do bash -n \"\$f\" 2>&1; [ \$? -le 2 ] || rc=1; done; exit \$rc' sh {} +" 0 40
  skip shell-lint code-quality "shellcheck NOT installed — only bash -n syntax checking ran; style and quoting defects were NOT looked for"
fi

# ---------------------------------------------------------------- testing
probe test-inventory testing \
  "find . $PRUNE -type d \\( -name test -o -name tests -o -name spec -o -name __tests__ \\) -print" 0 20
# Counted by NUL, not newline: a filename containing a newline is one file.
probe test-file-count testing \
  "find . $PRUNE -type f \\( -name '*test*.php' -o -name '*_test.go' -o -name '*.test.js' -o -name '*.test.ts' -o -name 'test_*.py' -o -name '*_spec.rb' -o -name 'test_*.sh' -o -name '*_test.sh' \\) -print0 | tr -dc '\\000' | wc -c | tr -d ' '"
probe ci-config testing \
  "find . -maxdepth 3 $PRUNE \\( -path './.github/workflows/*' -o -path ./.gitlab-ci.yml -o -path './.circleci/*' -o -path ./Jenkinsfile -o -path ./.travis.yml -o -path ./azure-pipelines.yml \\) -print | sort"
probe ci-badges testing \
  "grep -rhoE '!\\[[^]]*\\]\\(https://[^)]*(badge|shield|workflow|actions)[^)]*\\)' --include='*.md' $GREP_EX ." '0 1' 20

# ---------------------------------------------------------------- observability
probe health-endpoints observability \
  "grep -rlIE '(healthz|livez|readyz|/health|/ready|HealthCheck)' --include='*.php' --include='*.js' --include='*.ts' --include='*.py' --include='*.go' $GREP_EX . | grep -viE '(node_modules|vendor)'" '0 1' 20
probe log-surface observability \
  "grep -rhoIE '(Monolog|winston|pino|logrus|zap|structlog|SystemLogger|EventAuditLogger)' --include='*.php' --include='*.js' --include='*.ts' --include='*.py' --include='*.go' $GREP_EX . | sort | uniq -c | sort -rn" '0 1' 20
probe telemetry observability \
  "grep -rlIE '(opentelemetry|OTEL_|prometheus|statsd|datadog|langfuse|phoenix)' --include='*.php' --include='*.js' --include='*.ts' --include='*.py' --include='*.go' --include='*.y*ml' $GREP_EX . | grep -viE '(node_modules|vendor)'" '0 1' 20
probe swallowed-exceptions observability \
  "grep -rnIE -A1 'catch[[:space:]]*\\(' --include='*.php' --include='*.js' --include='*.ts' $GREP_EX . | grep -E '^\\S+[-:][0-9]+[-:][[:space:]]*\\}' | grep -viE '(node_modules|vendor|test)'" '0 1' 30

# ---------------------------------------------------------------- size & shape
probe repo-size performance 'du -sh . | cut -f1'
probe largest-files performance \
  "find . $PRUNE -type f -exec $STAT_SIZE {} + | sort -rn" 0 15
probe file-count performance "find . $PRUNE -type f -print0 | tr -dc '\\000' | wc -c | tr -d ' '"

# ---------------------------------------------------------------- compliance
probe license-files compliance \
  "find . -maxdepth 1 \\( -name 'LICENSE*' -o -name 'COPYING*' -o -name 'NOTICE*' \\) -print | sort"
if exists package.json && has npm; then
  probe dep-licenses compliance 'npm ls --json --depth=0' '0 1'
else
  skip dep-licenses compliance "no package.json, or npm not on PATH"
fi

# ---------------------------------------------------------------- summary
{
  echo "probe.sh summary"
  echo
  awk -F'\t' 'NR>1 {c[$3]++} END {for (s in c) printf "  %-7s %d\n", s, c[s]}' "$MANIFEST" | sort
  echo
  echo "  total   $(($(wc -l < "$MANIFEST") - 1))"
  T=$(awk -F'\t' 'NR>1 && $9 ~ /^TRUNCATED/' "$MANIFEST" | wc -l | tr -d ' ')
  E=$(awk -F'\t' 'NR>1 && $7=="yes"' "$MANIFEST" | wc -l | tr -d ' ')
  O=$(awk -F'\t' 'NR>1 && $3=="output"' "$MANIFEST" | wc -l | tr -d ' ')
  [ "$T" -gt 0 ] && echo "  WARN    $T probe(s) exceeded their line cap — full output in out/*.full.txt"
  [ "$E" -gt 0 ] && echo "  WARN    $E probe(s) wrote stderr — see out/*.err"
  [ "$O" -gt 0 ] && echo "  NOTE    $O probe(s) exited nonzero WITH output — read them, do not discard"
  [ -n "$TIMEOUT_BIN" ] || [ "$PTIMEOUT" = "0" ] || echo "  WARN    no timeout binary — probes ran unbounded (see env.txt)"
  echo
  echo "  bundle holds raw config and possible secrets — delete it when done."
} > "$BUNDLE/summary.txt"

cat "$BUNDLE/summary.txt" >&2
echo "$BUNDLE"
