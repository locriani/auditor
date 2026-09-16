#!/usr/bin/env bash
#
# probe.sh — one-pass evidence collection for a codebase audit.
#
#   probe.sh <target-dir> [-o <bundle-dir>] [--host-containers] [--timeout N]
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
# "empty" and "error" are never the same value, and a probe that cannot fail is
# never reported as clean. Collapsing those is Empty-Result Ambiguity — the first
# defect class this tool exists to hunt, and one this script committed in v1.0.0
# by suffixing 17 probes with `|| true`.
#
# Exit codes: 0 the run completed (findings are not failures)
#             2 usage error, or the target does not exist
#
# Written for bash 3.2 (macOS system bash) — no associative arrays, no mapfile.

set -eu

TARGET=""; BUNDLE=""; HOST_CONTAINERS=0; PTIMEOUT="120"   # seconds per probe; --timeout 0 disables

usage() { sed -n '3,6p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }

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
# The timeout value is interpolated into an `eval`d command string, so anything
# other than digits is code. v1.2.0 accepted it raw: `--timeout '1; cmd'` ran cmd
# once per probe. Validated here, before any file is written.
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
# to the network; without this a hung daemon hangs the whole collection.
TIMEOUT_CMD=""
if [ -n "$PTIMEOUT" ] && [ "$PTIMEOUT" != "0" ]; then
  if command -v timeout >/dev/null 2>&1; then TIMEOUT_CMD="timeout $PTIMEOUT"
  elif command -v gtimeout >/dev/null 2>&1; then TIMEOUT_CMD="gtimeout $PTIMEOUT"
  fi
fi

# probe <name> <axis> <cmd> [ok_exits] [cap]
#
# ok_exits  space-separated exit codes that mean "ran correctly" (default "0").
#           grep and friends exit 1 for "no match", which is a RESULT, not a
#           failure — those probes pass "0 1".
# cap       the `head -N` limit inside cmd, if any. Output landing exactly on the
#           cap is flagged truncated, because a silently clipped list reads as a
#           complete one.
#
# pipefail is deliberately OFF inside the probe: these are pipelines ending in
# head/wc, and SIGPIPE from head made complete, valid output report as exit 141.
probe() {
  _name="$1"; _axis="$2"; _cmd="$3"; _ok="${4:-0}"; _cap="${5:-}"
  _out="$BUNDLE/out/$_name.txt"; _err="$BUNDLE/out/$_name.err"; _rc=0
  ( cd "$TARGET" && set +o pipefail && eval "$TIMEOUT_CMD $_cmd" ) >"$_out" 2>"$_err" || _rc=$?
  _bytes=$(wc -c < "$_out" | tr -d ' ')
  _lines=$(wc -l < "$_out" | tr -d ' ')
  if [ -s "$_err" ]; then _haserr="yes"; else _haserr="no"; rm -f "$_err"; fi

  _expected=0
  for _c in $_ok; do [ "$_rc" = "$_c" ] && _expected=1; done

  if [ "$_expected" -eq 1 ]; then
    if [ "$_bytes" -eq 0 ]; then
      _status="empty"; _note="ran clean, produced no output"
    else
      _status="ok"; _note="see output file"
    fi
  elif [ "$_bytes" -gt 0 ]; then
    # The npm-audit case: nonzero BECAUSE it found something.
    _status="output"
    _note="exited $_rc and produced output — read it, do not discard"
  else
    _status="error"
    _note=$(head -c 160 "$_err" 2>/dev/null | tr '\n\t' '  ' | sed 's/  */ /g')
    [ -n "$_note" ] || _note="exited $_rc with no stderr"
  fi

  if [ -n "$_cap" ] && [ "$_lines" -ge "$_cap" ]; then
    _note="TRUNCATED at $_cap lines — more exists. $_note"
  fi
  if [ "$_haserr" = "yes" ] && [ "$_status" != "error" ]; then
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

PRUNE='-not -path "./.git/*" -not -path "./node_modules/*" -not -path "./vendor/*"'
# grep -r ignores find's prune, so vendored and generated trees have to be excluded
# explicitly or they dominate every result set. Minified files are excluded by name:
# a single 400KB line of bundled JS matches almost any pattern and proves nothing.
GREP_EX='--exclude-dir=.git --exclude-dir=node_modules --exclude-dir=vendor --exclude-dir=dist --exclude-dir=build --exclude-dir=coverage --exclude-dir=.venv --exclude-dir=__pycache__ --exclude-dir=third_party --exclude-dir=jquery --exclude=*.min.js --exclude=*.min.css --exclude=*.map --exclude=*-lock.json --exclude=*.lock'

{
  echo "target:     $TARGET"
  echo "collected:  $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  echo "host:       $(uname -srm)"
  echo "bash:       ${BASH_VERSION:-unknown}"
  echo "host-containers: $HOST_CONTAINERS"
  echo "timeout:    ${PTIMEOUT:-none}"
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
  probe git-log          supply-chain 'git log --oneline -40 -- .' 0 40
  probe git-commit-count supply-chain 'git rev-list --count HEAD -- .'
  probe git-authors      supply-chain 'git shortlog -sne HEAD -- .'
  probe git-status       supply-chain 'git status --short -- .'
  probe git-tracked      supply-chain 'git ls-files -- . | head -40' 0 40
  probe git-tags         supply-chain 'git tag --list | head -40' 0 40
  probe git-submodules   supply-chain 'test -f .gitmodules && cat .gitmodules' '0 1'
  probe git-churn        code-quality \
    'git log --format=format: --name-only -- . | grep -v "^$" | sort | uniq -c | sort -rn | head -25' '0 1' 25
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
  if has npm; then probe npm-audit supply-chain 'npm audit --json' '0 1'
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
probe dockerfiles supply-chain \
  "find . -name 'Dockerfile*' $PRUNE | head -20" '0 1' 20
probe dockerfile-fetches supply-chain \
  "find . -name 'Dockerfile*' $PRUNE -exec grep -Hn -E '(git clone|curl|wget|ADD https?://)' {} +" '0 1'
probe compose-files supply-chain \
  "find . \\( -name 'docker-compose*.y*ml' -o -name 'compose.y*ml' \\) $PRUNE | head -20" '0 1' 20

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
# NOTE: the include list is narrow. An `empty` here means "no assigned literal in
# THESE extensions", never "no secrets". The note says so, because a reader who
# takes it for the latter has been misled by the tool.
SECRET_INC='--include="*.y*ml" --include="*.env*" --include="*.json" --include="*.ini" --include="*.conf" --include="*.cfg" --include="*.toml" --include="*.xml" --include="*.properties" --include="*.sh" --include="*.php" --include="*.ts" --include="*.js" --include="*.py" --include="*.rb" --include="*.go" --include="*.tf"'
probe secret-scan security \
  "grep -rInE '(password|passwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key)[[:space:]]*[:=][[:space:]]*\"?'\"'\"'?[A-Za-z0-9_./+=-]{6,}' $SECRET_INC $GREP_EX . | grep -viE '(example|sample|placeholder|changeme|your[_-]|xxx|csrf|jquery|function|typeof|prototype|[$][{]|[$][A-Z_]+)' | head -40" '0 1' 40
probe env-files security "find . -name '.env*' $PRUNE | head -20" '0 1' 20
probe published-ports security \
  "grep -rhnE '^[[:space:]]*-[[:space:]]*\"?[0-9]{2,5}:[0-9]{2,5}' --include='docker-compose*.y*ml' --include='compose*.y*ml' $GREP_EX . | head -40" '0 1' 40

# ---------------------------------------------------------------- surface
probe route-tables architecture \
  "grep -rlIE '(GET|POST|PUT|PATCH|DELETE)[[:space:]]+/' --include='*.php' --include='*.js' --include='*.ts' --include='*.py' --include='*.rb' --include='*.go' $GREP_EX . | grep -viE '(node_modules|vendor|test|spec)' | head -20" '0 1' 20
probe route-verbs architecture \
  "grep -rhoIE '\"(GET|POST|PUT|PATCH|DELETE) /[A-Za-z0-9_/:.-]*\"' --include='*.php' --include='*.inc.php' --include='*.js' --include='*.ts' $GREP_EX . | tr -d '\"' | awk '{print \$1}' | sort | uniq -c | sort -rn | head -20" '0 1' 20

# ---------------------------------------------------------------- declared standard
probe lint-config code-quality \
  'ls -1 .editorconfig .eslintrc* eslint.config.* .prettierrc* phpcs.xml* .php-cs-fixer* psalm.xml* phpstan.neon* ruff.toml .flake8 setup.cfg tox.ini rustfmt.toml .golangci.y*ml .rubocop.yml 2>/dev/null' '0 1 2'
probe lang-census code-quality \
  "find . -type f -name '*.*' $PRUNE | sed 's/.*\\.//' | sort | uniq -c | sort -rn | head -20" 0 20
if exists composer.json && has php; then
  probe php-syntax code-quality \
    "find . -name '*.php' -not -path './vendor/*' -print0 | xargs -0 -n1 php -l 2>&1 | grep -v 'No syntax errors' | head -40" '0 1' 40
else
  skip php-syntax code-quality "no composer.json, or php not on PATH"
fi
# shellcheck absence is a DOWNGRADE, not a clean result — say which ran.
if has shellcheck; then
  probe shell-lint code-quality "find . -name '*.sh' $PRUNE -exec shellcheck -f gcc {} + | head -60" '0 1' 60
else
  probe shell-syntax-only code-quality \
    "find . -name '*.sh' $PRUNE -print0 | xargs -0 -n1 bash -n 2>&1 | head -40" '0 1' 40
  skip shell-lint code-quality "shellcheck NOT installed — only bash -n syntax checking ran; style and quoting defects were NOT looked for"
fi

# ---------------------------------------------------------------- testing
probe test-inventory testing \
  "find . -type d \\( -name test -o -name tests -o -name spec -o -name __tests__ \\) $PRUNE | head -20" '0 1' 20
probe test-file-count testing \
  "find . -type f \\( -name '*test*.php' -o -name '*_test.go' -o -name '*.test.js' -o -name '*.test.ts' -o -name 'test_*.py' -o -name '*_spec.rb' \\) $PRUNE | wc -l | tr -d ' '"
probe ci-config testing 'ls -1 .github/workflows/ .gitlab-ci.yml .circleci/ Jenkinsfile .travis.yml azure-pipelines.yml 2>/dev/null' '0 1 2'
probe ci-badges testing \
  "grep -rhoE '!\\[[^]]*\\]\\(https://[^)]*(badge|shield|workflow|actions)[^)]*\\)' --include='*.md' $GREP_EX . | head -20" '0 1' 20

# ---------------------------------------------------------------- observability
probe health-endpoints observability \
  "grep -rlIE '(healthz|livez|readyz|/health|/ready|HealthCheck)' --include='*.php' --include='*.js' --include='*.ts' --include='*.py' --include='*.go' $GREP_EX . | grep -viE '(node_modules|vendor)' | head -20" '0 1' 20
probe log-surface observability \
  "grep -rhoIE '(Monolog|winston|pino|logrus|zap|structlog|SystemLogger|EventAuditLogger)' --include='*.php' --include='*.js' --include='*.ts' --include='*.py' --include='*.go' $GREP_EX . | sort | uniq -c | sort -rn | head -20" '0 1' 20
probe telemetry observability \
  "grep -rlIE '(opentelemetry|OTEL_|prometheus|statsd|datadog|langfuse|phoenix)' --include='*.php' --include='*.js' --include='*.ts' --include='*.py' --include='*.go' --include='*.y*ml' $GREP_EX . | grep -viE '(node_modules|vendor)' | head -20" '0 1' 20
probe swallowed-exceptions observability \
  "grep -rnIE -A1 'catch[[:space:]]*\\(' --include='*.php' --include='*.js' --include='*.ts' $GREP_EX . | grep -E '^\\S+[-:][0-9]+[-:][[:space:]]*\\}' | grep -viE '(node_modules|vendor|test)' | head -30" '0 1' 30

# ---------------------------------------------------------------- size & shape
probe repo-size performance 'du -sh . | cut -f1'
probe largest-files performance \
  "find . -type f $PRUNE -exec ls -l {} + | sort -k5 -rn | head -15 | awk '{print \$5, \$9}'" '0 1' 15
probe file-count performance "find . -type f $PRUNE | wc -l | tr -d ' '"

# ---------------------------------------------------------------- compliance
probe license-files compliance 'ls -1 LICENSE* COPYING* NOTICE* 2>/dev/null' '0 1 2'
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
  [ "$T" -gt 0 ] && echo "  WARN    $T probe(s) hit their line cap — output is incomplete"
  [ "$E" -gt 0 ] && echo "  WARN    $E probe(s) wrote stderr — see out/*.err"
  [ "$O" -gt 0 ] && echo "  NOTE    $O probe(s) exited nonzero WITH output — read them, do not discard"
  echo
  echo "  bundle holds raw config and possible secrets — delete it when done."
} > "$BUNDLE/summary.txt"

cat "$BUNDLE/summary.txt" >&2
echo "$BUNDLE"
