#!/usr/bin/env bash
#
# probe.sh — one-pass evidence collection for a codebase audit.
#
# Detects the stack rather than assuming it, runs every applicable probe once,
# and writes an evidence bundle plus manifest.tsv. Prints the bundle path.
#
# The manifest keeps five outcomes distinct, which is the whole point:
#   ok      ran, found something          empty  ran, output nothing
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
# The bundle holds every secret-scan hit. v1.3.0 wrote it at the caller's umask,
# so on a shared Linux /tmp any local account could read it.
umask 077
# With CDPATH exported, `cd dir` prints the directory it chose and may choose a
# same-named directory elsewhere. v1.3.0 captured that output as the target.
unset CDPATH

TARGET=""; BUNDLE=""; HOST_CONTAINERS=0; RUN_TOOLCHAINS=0; PTIMEOUT="120"   # seconds per probe; --timeout 0 disables

# The synopsis lives here, not in the header. v1.0.0–1.2.x printed it with
# `sed -n '3,6p' "$0"`, which went wrong the first time the header moved.
usage() {
  cat <<'USAGE'
probe.sh <target-dir> [-o <bundle-dir>] [--run-toolchains] [--host-containers] [--timeout N]

  -o <dir>            new or empty directory you own, outside the target, or a
                      bundle probe.sh created before
  --run-toolchains    also run dependency scanners (composer, npm, pip-audit,
                      govulncheck, cargo-audit, bundler-audit). They honour config
                      the target ships and can run its code: use only inside a
                      disposable container over a copy (off by default)
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
    --run-toolchains) RUN_TOOLCHAINS=1; shift ;;
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
# `00` compared unequal to `0` and was recorded as enforced, though timeout(1)
# treats it as disabled; a 20-digit value was passed through to it unchecked.
PTIMEOUT=$(printf '%s' "$PTIMEOUT" | sed 's/^0*//'); PTIMEOUT="${PTIMEOUT:-0}"
[ "${#PTIMEOUT}" -le 6 ] || { echo "invalid --timeout: more than 999999 seconds" >&2; exit 2; }
[ -d "$TARGET" ] || { echo "not a directory: $TARGET" >&2; exit 2; }
TARGET=$(cd -P -- "$TARGET" >/dev/null && pwd -P)

# resolve_path <path> — absolute, symlinks resolved through the deepest ancestor
# that exists. The remainder does not exist yet, so it cannot be a symlink.
resolve_path() {
  _p="$1"; _rest=""
  case "$_p" in /*) ;; *) _p="$PWD/$_p" ;; esac
  while [ ! -d "$_p" ]; do _rest="/$(basename "$_p")$_rest"; _p=$(dirname "$_p"); done
  printf '%s%s\n' "$(cd -P -- "$_p" >/dev/null && pwd -P)" "$_rest"
}

if [ -z "$BUNDLE" ]; then
  # mktemp, not a name derived from the clock: v1.3.0's name was predictable to
  # the second, and a directory another account created there was adopted.
  BUNDLE=$(mktemp -d "${TMPDIR:-/tmp}/codebase-audit-$(basename "$TARGET")-$(date +%Y%m%d-%H%M%S).XXXXXX")
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
# A bundle inside the target is walked by the probes while it is being written,
# and writing it modifies the tree under audit.
case "$(resolve_path "$BUNDLE")/" in
  "$TARGET"/*) echo "refusing: bundle $BUNDLE is inside the target $TARGET. Nothing was modified." >&2; exit 2 ;;
esac
# Another account's directory can be read, swapped or rewritten by that account.
if [ -d "$BUNDLE" ] && [ ! -O "$BUNDLE" ]; then
  echo "refusing: $BUNDLE is owned by another account. Nothing was modified." >&2; exit 2
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
chmod 700 "$BUNDLE"
printf 'created by codebase-audit probe.sh; safe for probe.sh to clear on reuse\n' > "$BUNDLE/$MARKER"
MANIFEST="$BUNDLE/manifest.tsv"
printf 'probe\taxis\tstatus\texit\tbytes\tlines\tstderr\tfile\tnote\n' > "$MANIFEST"

# A timeout guard, where one is available. Two probes talk to a daemon and every
# scanner under --run-toolchains to the network; without this a hung daemon or
# registry hangs the whole collection. Stock macOS has neither binary, and env.txt
# records which case applied.
TIMEOUT_BIN=""
if [ "$PTIMEOUT" != "0" ]; then
  if command -v timeout >/dev/null 2>&1; then TIMEOUT_BIN="timeout"
  elif command -v gtimeout >/dev/null 2>&1; then TIMEOUT_BIN="gtimeout"
  fi
fi
TIMEOUT_PREFIX=""; [ -z "$TIMEOUT_BIN" ] || TIMEOUT_PREFIX="$TIMEOUT_BIN $PTIMEOUT"

# Per-file checkers run this many at once. php -l is one process per file, and run
# serially over 4,607 files it ran past the 120-second cap.
JOBS=$(getconf _NPROCESSORS_ONLN 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)
case "$JOBS" in ''|*[!0-9]*) JOBS=4 ;; esac
[ "$JOBS" -ge 4 ] || JOBS=4

# probe <name> <axis> <cmd> [ok_exits] [cap] [valid_if] [empty_note]
#
# ok_exits   space-separated exit codes that mean "ran correctly" (default "0").
#            grep exits 1 for "no match" and scanners exit nonzero when they
#            find something — RESULTS, not failures.
# cap        lines kept in out/<name>.txt. More than that is flagged TRUNCATED and
#            the whole output is kept in out/<name>.full.txt. Commands must not
#            cap themselves with `| head`: that pins the pipeline's exit status
#            to head's, which is how v1.2.0's `exit` column came to report 0 for
#            24 of 39 probes whatever the producer did.
# valid_if   an extended regex the output must contain to count as a report. For
#            tools whose "found something" exit is also their "could not run"
#            exit, only the content can separate the two. v1.2.0 filed npm's
#            ENOLOCK as `ok`; v1.3.0 matched ENOLOCK's shape and still filed an
#            unreachable registry `ok`, so the check is now on what a report
#            contains, not on what one failure looked like.
# empty_note appended to an `empty` row's note, where "ran clean" would overclaim.
#
# Each command runs in its own bash with pipefail ON, so any producing stage
# failing is the probe failing. A trailing `grep -v` filter must be written as
# `{ grep -v … || [ $? -eq 1 ]; }`, or its "nothing survived" exit replaces the
# producer's. (pipefail was off in v1.2.x to stop `head` SIGPIPE reading as
# exit 141; with the cap moved here there is no `head` to cause it.) The command
# is passed to that bash as one argument, never eval'd, and the timeout binary
# wraps the whole of it — v1.2.0's `timeout 120 for c in …` was a syntax error.
probe() {
  _name="$1"; _axis="$2"; _cmd="$3"; _ok="${4:-0}"; _cap="${5:-}"; _validpat="${6:-}"; _emptynote="${7:-}"
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
  elif [ -n "$_validpat" ] && ! grep -qE "$_validpat" "$_out"; then
    _status="error"
    _said=$(grep -oE '"(message|code|summary)"[[:space:]]*:[[:space:]]*"[^"]+"' "$_out" | head -1)
    [ -n "$_said" ] || _said=$(cat "$_out" "$_err" 2>/dev/null | grep -v '^[[:space:]]*[{}]*[[:space:]]*$' | head -1)
    _note="exited $_rc and printed no report ($(printf '%s' "$_said" | tr '\t' ' ' | cut -c1-120)) — out/$_name.txt holds its error, not results"
  elif [ "$_expected" -eq 1 ]; then
    if [ "$_bytes" -eq 0 ] && [ "$_haserr" = "yes" ]; then
      _status="empty"; _note="produced no output, but wrote stderr — read out/$_name.err before concluding none${_emptynote:+. $_emptynote}"
    elif [ "$_bytes" -eq 0 ]; then
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
  if [ "$_haserr" = "yes" ] && [ "$_status" != "empty" ]; then
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

# gated <name> <axis> — a probe withheld because it can execute what the target
# ships. `error`, not `n/a`: the area is unexamined, and the audit must say so.
# v1.3.0 ran `cargo audit` through a committed alias and filed the row clean.
gated() {
  printf '%s\t%s\terror\t-\t0\t0\tno\t-\t%s\n' "$1" "$2" \
    "not run: target-supplied toolchain config can execute code — pass --run-toolchains, inside a disposable container over a copy" >> "$MANIFEST"
}

has() { command -v "$1" >/dev/null 2>&1; }
exists() { [ -e "$TARGET/$1" ]; }

# A real prune, at any depth. v1.2.0 used `-not -path "./node_modules/*"`, which
# matches only at the root — nested vendor trees leaked into every count — and
# still walked .git, so git housekeeping mid-run filled the stderr column with
# noise. Every find using this must end its own expression with an action.
#
# One list feeds both find's prune and grep's excludes. In v1.3.0 find pruned three
# names and grep excluded ten, so counts in the same bundle described a different
# tree from matches: 21 first-party files beside a .venv counted as 3023.
SKIP_DIRS=".git node_modules vendor dist build coverage .venv venv __pycache__ third_party bower_components target jquery"
PRUNE=""; GREP_EX=""
for _d in $SKIP_DIRS; do
  PRUNE="$PRUNE${PRUNE:+ -o }-name $_d"; GREP_EX="$GREP_EX --exclude-dir=$_d"
done
PRUNE="\\( $PRUNE \\) -prune -o"
# Minified files are excluded by name: a single 400KB line of bundled JS matches
# almost any pattern and proves nothing.
FILE_EX='--exclude="*.min.js" --exclude="*.min.css" --exclude="*.map" --exclude="*-lock.json" --exclude="*.lock"'
GREP_EX="$GREP_EX $FILE_EX"
# secret-scan skips only what cannot hold the target's own secrets. A build/ or
# dist/ directory holding a .env is exactly where one leaks.
SECRET_EX="--exclude-dir=.git --exclude-dir=node_modules --exclude-dir=vendor $FILE_EX"

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
  if [ "$RUN_TOOLCHAINS" -eq 1 ]; then
    echo "toolchains: run (--run-toolchains) — scanners honoured the target's own config"
  else
    echo "toolchains: NOT RUN — dependency scanners and git-status were withheld; see their error rows"
  fi
  if [ -n "$TIMEOUT_BIN" ]; then
    echo "timeout:    ${PTIMEOUT}s per probe, enforced by $TIMEOUT_BIN"
  elif [ "$PTIMEOUT" = "0" ]; then
    echo "timeout:    none — disabled with --timeout 0"
  else
    echo "timeout:    NONE ENFORCED — ${PTIMEOUT}s requested, but neither timeout nor gtimeout is on PATH; probes ran unbounded"
  fi
  echo "secret-scan reads: $SECRET_GLOBS"
  echo "checker jobs: $JOBS"
} > "$BUNDLE/env.txt"

# ---------------------------------------------------------------- provenance
# `[ -d .git ]` was wrong: a target inside a work tree with no .git of its own
# reported "not version controlled", which is a different claim entirely.
GITSCOPE=""
# A target's .git/config can name commands git runs on read: core.fsmonitor (in
# status and ls-files) and gpg.program under log.showSignature (in log). Both are
# overridden here. A clean filter declared in .git/info/attributes runs during
# `git status` and cannot be switched off from the command line, so git-status
# is gated and git-staged / git-untracked, which never read file content, replace it.
GIT="git -c core.fsmonitor=false -c log.showSignature=false"
if has git && ( cd "$TARGET" && $GIT rev-parse --is-inside-work-tree ) >/dev/null 2>&1; then
  GITROOT=$( cd "$TARGET" && $GIT rev-parse --show-toplevel )
  if [ "$GITROOT" = "$TARGET" ]; then GITSCOPE="repo root"; else GITSCOPE="subdirectory of $GITROOT"; fi
  echo "git scope:  $GITSCOPE" >> "$BUNDLE/env.txt"
  probe git-remotes      supply-chain "$GIT remote -v"
  # -41 against a cap of 40: one line past the cap is how the probe knows more exists.
  probe git-log          supply-chain "$GIT log --oneline -41 -- ." 0 40
  probe git-commit-count supply-chain "$GIT rev-list --count HEAD -- ."
  probe git-authors      supply-chain "$GIT shortlog -sne HEAD -- ."
  if [ "$RUN_TOOLCHAINS" -eq 1 ]; then probe git-status supply-chain "$GIT status --short -- ."
  else gated git-status supply-chain; fi
  probe git-staged       supply-chain "$GIT diff-index --cached --name-status HEAD -- ." 0 40
  probe git-untracked    supply-chain "$GIT ls-files --others --exclude-standard -- ." 0 40
  probe git-tracked      supply-chain "$GIT ls-files -- ." 0 40
  probe git-tags         supply-chain "$GIT tag --list" 0 40
  probe git-submodules   supply-chain 'test -f .gitmodules && cat .gitmodules' '0 1'
  probe git-churn        code-quality \
    "$GIT log --format=format: --name-only -- . | grep -v '^\$' | sort | uniq -c | sort -rn" '0 1' 25
else
  for p in git-remotes git-log git-commit-count git-authors git-status git-staged git-untracked git-tracked git-tags git-submodules; do
    skip "$p" supply-chain "not inside a git work tree, or git not installed"
  done
  skip git-churn code-quality "no git history to mine"
fi

# ---------------------------------------------------------------- dependencies
# Every scanner below reads configuration the target ships, and several run it:
# a cargo alias, a composer plugin, a Gemfile, a go.mod toolchain line, a
# pyproject build backend. They run only with --run-toolchains, and then with each
# route that has a command-line off switch switched off. The rest are listed in
# SKILL.md under "What probe.sh does not guarantee".
DEPS=0
if exists composer.json; then DEPS=1
  probe composer-manifest supply-chain 'cat composer.json'
  if [ "$RUN_TOOLCHAINS" -eq 0 ]; then gated composer-audit supply-chain
  elif has composer; then probe composer-audit supply-chain 'composer audit --format=plain --no-interaction --no-plugins --no-scripts' '0 1 2'
  else skip composer-audit supply-chain "composer.json present but composer not on PATH"; fi
fi
if exists package.json; then DEPS=1
  probe npm-manifest supply-chain 'cat package.json'
  # npm audit exits 1 when it FINDS vulnerabilities. That is the finding.
  # It also exits 1 when it cannot audit at all (ENOLOCK: no lockfile), and
  # prints a JSON error object to stdout — so the content decides, not the exit.
  # --registry on the command line outranks a registry set in the target's .npmrc.
  if [ "$RUN_TOOLCHAINS" -eq 0 ]; then gated npm-audit supply-chain
  elif has npm; then probe npm-audit supply-chain 'npm audit --json --registry=https://registry.npmjs.org/' '0 1' '' '"(auditReportVersion|vulnerabilities)"[[:space:]]*:'
  else skip npm-audit supply-chain "package.json present but npm not on PATH"; fi
fi
if exists requirements.txt || exists pyproject.toml; then DEPS=1
  # With no arguments pip-audit audits the Python environment it is installed in,
  # not the target. v1.3.0 reported a Django 2.2 target clean that way.
  if [ "$RUN_TOOLCHAINS" -eq 0 ]; then gated pip-audit supply-chain
  elif ! has pip-audit; then skip pip-audit supply-chain "python manifest present but pip-audit not installed"
  elif exists requirements.txt; then probe pip-audit supply-chain 'pip-audit -r requirements.txt -f json --progress-spinner off' '0 1' '' '"dependencies"[[:space:]]*:'
  else probe pip-audit supply-chain 'pip-audit -f json --progress-spinner off .' '0 1' '' '"dependencies"[[:space:]]*:'; fi
fi
if exists go.mod; then DEPS=1
  # GOTOOLCHAIN=local: a go.mod `toolchain` line otherwise downloads and runs that Go.
  if [ "$RUN_TOOLCHAINS" -eq 0 ]; then gated go-vulncheck supply-chain
  elif has govulncheck; then probe go-vulncheck supply-chain 'GOTOOLCHAIN=local govulncheck ./...' '0 3'
  else skip go-vulncheck supply-chain "go.mod present but govulncheck not installed"; fi
fi
if exists Cargo.toml; then DEPS=1
  # cargo-audit directly: `cargo audit` resolves aliases from the target's .cargo/config.toml.
  if [ "$RUN_TOOLCHAINS" -eq 0 ]; then gated cargo-audit supply-chain
  elif has cargo-audit; then probe cargo-audit supply-chain 'cargo-audit audit' '0 1'
  else skip cargo-audit supply-chain "Cargo.toml present but cargo-audit not installed"; fi
fi
if exists Gemfile; then DEPS=1
  # bundler-audit directly reads Gemfile.lock; `bundle audit` goes through bundler.
  if [ "$RUN_TOOLCHAINS" -eq 0 ]; then gated bundler-audit supply-chain
  elif has bundler-audit; then probe bundler-audit supply-chain 'bundler-audit check --update' '0 1'
  else skip bundler-audit supply-chain "Gemfile present but bundler-audit not installed"; fi
fi
[ "$DEPS" -eq 1 ] || skip dependency-audit supply-chain "no recognised package manifest at the target root"

# ---------------------------------------------------------------- build inputs
# find exits 1 only when it could not read something, so find probes accept 0 alone.
# Build definitions by every common name, not just Dockerfile*. Fetches include a
# base image that floats: `:latest`, or no tag at all, which means `:latest`.
# Instructions are case-insensitive, so the pattern is too.
DOCKER_INC="--include='Dockerfile*' --include='*.Dockerfile' --include='*.dockerfile' --include='Containerfile*'"
probe dockerfiles supply-chain \
  "find . $PRUNE \\( -name 'Dockerfile*' -o -name '*.Dockerfile' -o -name '*.dockerfile' -o -name 'Containerfile*' \\) -print" 0 20
probe dockerfile-fetches supply-chain \
  "grep -rHniE '(git clone|curl|wget|ADD[[:space:]]+https?://|^[[:space:]]*FROM([[:space:]]+--[^[:space:]]+)*[[:space:]]+[^[:space:]]+:latest([[:space:]]|\$)|^[[:space:]]*FROM([[:space:]]+--[^[:space:]]+)*[[:space:]]+[^:@[:space:]]+([[:space:]]+AS[[:space:]]+[^[:space:]]+)?[[:space:]]*\$)' $DOCKER_INC $GREP_EX ." '0 1'
probe compose-files supply-chain \
  "find . $PRUNE \\( -name 'docker-compose*.y*ml' -o -name 'compose.y*ml' \\) -print" 0 20

# ---------------------------------------------------------------- runtime
# Opt-in only. A filename match inside the target is NOT consent to enumerate
# and exec into every container on the host — that is evidence about the machine,
# not about the tree, and v1.0.0 did it by default.
if [ "$HOST_CONTAINERS" -eq 1 ] && has docker; then
  probe docker-ps observability 'docker ps --format "{{.Names}}\t{{.Status}}\t{{.Image}}\t{{.Ports}}"'
  # An exec that fails says nothing about which clients exist, so it is reported
  # on stderr and fails the probe. v1.3.0 discarded it and filed `empty`.
  probe db-clients data-quality \
    'cs=$(docker ps --format "{{.Names}}") || exit 1; rc=0; for c in $cs; do if docker exec "$c" true >/dev/null; then docker exec "$c" sh -c "for b in mariadb mysql psql mongosh sqlite3 redis-cli; do command -v \$b >/dev/null 2>&1 && echo \$b; done; true" | sed "s/^/$c: /"; else echo "$c: docker exec failed — which clients it has is unknown" >&2; rc=1; fi; done; exit $rc'
else
  skip docker-ps  observability "host container inspection is opt-in; pass --host-containers"
  skip db-clients data-quality  "host container inspection is opt-in; pass --host-containers"
fi

# ---------------------------------------------------------------- secrets
# Case-insensitive: DB_PASSWORD= and AWS_SECRET_ACCESS_KEY= are the convention.
# A key may carry a suffix (SECRET_KEY, secretKey) and be quoted ("password":);
# the separator is :, = or =>, or a comma between two quotes (define('DB_PASSWORD',
# '…')). A plural (tokens) is not a key, and a bare comma is a list. URL credentials are
# a second shape. The placeholder filter reads only the content after path:line:,
# so a hit under examples/ or functions/ is kept. A `$` value is never a literal
# (the value class excludes it), so PHP's `$password = "…"` is no longer dropped.
# A value that is a call (`tokenExpiry = Date.now()`) is dropped: it is code.
# grep -v exits 1 when nothing survives it; `|| [ $? -eq 1 ]` keeps that from
# replacing grep -r's 2 when part of the tree could not be read.
probe secret-scan security \
  "grep -rIniE '((password|passwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key)([_-]?key|[_-][a-z0-9_-]*)?([\"'\"'\"']?[[:space:]]*(:|=>?)[[:space:]]*[\"'\"'\"']?|[\"'\"'\"'][[:space:]]*,[[:space:]]*[\"'\"'\"'])[A-Za-z0-9_./+=-]{6,}|[a-z][a-z0-9+.-]*://[^/:@[:space:]\"'\"'\"']+:[^/@[:space:]\"'\"'\"']{6,}@)' $SECRET_INC $SECRET_EX . | { grep -viE '^[^:]*:[0-9]+:.*(example|sample|placeholder|changeme|your[_-]|xxx|csrf|jquery|function|typeof|prototype|(password|passwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key)([_-]?key|[_-][a-z0-9_-]*)?[\"'\"'\"']?[[:space:]]*(:|=>?)[[:space:]]*[A-Za-z_][A-Za-z0-9_.]*[(])' || [ \$? -eq 1 ]; }" '0 1' 40 '' \
  "the pattern matched nothing in the file types listed in env.txt. It finds one-line assignments and URL credentials only (SKILL.md, What probe.sh does not guarantee) — this is not evidence of no secrets"
probe env-files security "find . $PRUNE -name '.env*' -print" 0 20
probe published-ports security \
  "grep -rhnE '^[[:space:]]*-[[:space:]]*\"?[0-9]{2,5}:[0-9]{2,5}' --include='docker-compose*.y*ml' --include='compose*.y*ml' $GREP_EX ." '0 1' 40

# ---------------------------------------------------------------- surface
probe route-tables architecture \
  "grep -rlIE '(GET|POST|PUT|PATCH|DELETE)[[:space:]]+/' --include='*.php' --include='*.js' --include='*.ts' --include='*.py' --include='*.rb' --include='*.go' $GREP_EX . | { grep -viE '(node_modules|vendor|test|spec)' || [ \$? -eq 1 ]; }" '0 1' 20
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
    "find . $PRUNE -name '*.php' -print0 | xargs -0 -n 1 -P $JOBS sh -c 'rc=0; for f; do php -l \"\$f\" 2>&1; case \$? in 0|255) ;; *) rc=1 ;; esac; done; exit \$rc' sh | awk '!/^No syntax errors/'" 0 40
else
  skip php-syntax code-quality "no composer.json, or php not on PATH"
fi
# Absence of shellcheck is a DOWNGRADE, not a clean result — say which ran.
#
# Checkers run inside `sh -c`, which maps "the checker found something" (php -l
# 255, shellcheck 1, bash -n 2) to success and anything else to failure. php-syntax
# fans that wrapper out with `xargs -P`; the wrapper never exits 255, which would
# stop xargs, and any other failure leaves xargs nonzero, so the row is not `ok`.
# v1.3.0's xargs could not: BSD xargs reports every nonzero child as 1, the same
# exit as find failing to read a directory. Exit 1 from these probes now means
# only the latter.
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
  "grep -rlIE '(healthz|livez|readyz|/health|/ready|HealthCheck)' --include='*.php' --include='*.js' --include='*.ts' --include='*.py' --include='*.go' $GREP_EX . | { grep -viE '(node_modules|vendor)' || [ \$? -eq 1 ]; }" '0 1' 20
probe log-surface observability \
  "grep -rhoIE '(Monolog|winston|pino|logrus|zap|structlog|SystemLogger|EventAuditLogger)' --include='*.php' --include='*.js' --include='*.ts' --include='*.py' --include='*.go' $GREP_EX . | sort | uniq -c | sort -rn" '0 1' 20
probe telemetry observability \
  "grep -rlIE '(opentelemetry|OTEL_|prometheus|statsd|datadog|langfuse|phoenix)' --include='*.php' --include='*.js' --include='*.ts' --include='*.py' --include='*.go' --include='*.y*ml' $GREP_EX . | { grep -viE '(node_modules|vendor)' || [ \$? -eq 1 ]; }" '0 1' 20
probe swallowed-exceptions observability \
  "grep -rnIE -A1 'catch[[:space:]]*\\(' --include='*.php' --include='*.js' --include='*.ts' $GREP_EX . | { grep -E '^\\S+[-:][0-9]+[-:][[:space:]]*\\}' || [ \$? -eq 1 ]; } | { grep -viE '(node_modules|vendor|test)' || [ \$? -eq 1 ]; }" '0 1' 30

# ---------------------------------------------------------------- size & shape
probe repo-size performance 'du -sh . | cut -f1'
probe largest-files performance \
  "find . $PRUNE -type f -exec $STAT_SIZE {} + | sort -rn" 0 15
probe file-count performance "find . $PRUNE -type f -print0 | tr -dc '\\000' | wc -c | tr -d ' '"

# ---------------------------------------------------------------- compliance
probe license-files compliance \
  "find . -maxdepth 1 \\( -name 'LICENSE*' -o -name 'COPYING*' -o -name 'NOTICE*' \\) -print | sort"
if exists package.json && [ "$RUN_TOOLCHAINS" -eq 0 ]; then
  gated dep-licenses compliance
elif exists package.json && has npm; then
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
