#!/usr/bin/env bash
#
# test_probe.sh — tests for probe.sh's status classification.
#
#   bash test_probe.sh
#
# The classification is the whole contract: a reader acts on `empty` by writing
# "no X found" and on `error` by writing nothing at all. Getting those backwards
# is how an audit tool produces a confident false negative, so that is what these
# tests are for. No network, no docker, no fixtures outside a temp dir.

set -u
PROBE="$(cd "$(dirname "$0")" && pwd)/probe.sh"
TMP=$(mktemp -d); trap 'chmod -R u+rwX "$TMP" 2>/dev/null; rm -rf "$TMP"' EXIT
PASS=0; FAIL=0; SKIP=0
# Permission fixtures cannot fail as root: root reads a chmod 000 directory.
ROOT=0; [ "$(id -u)" = "0" ] && ROOT=1

ok()   { PASS=$((PASS+1)); printf '  ok    %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  FAIL  %s\n       expected: %s\n       actual:   %s\n' "$1" "$2" "$3"; }
skipped() { SKIP=$((SKIP+1)); printf '  skip  %s\n' "$1"; }
field() { awk -F'\t' -v n="$2" -v c="$3" 'NR>1 && $1==n {print $c}' "$1"; }
status_of() { field "$1" "$2" 3; }
note_of()   { field "$1" "$2" 9; }

run() { # run <target> [extra args...] -> echoes manifest path
  _b="$TMP/bundle-$RANDOM"
  bash "$PROBE" "$@" -o "$_b" >/dev/null 2>&1
  echo "$_b/manifest.tsv"
}

# Stub tools, put first on PATH only where a test names them. They stand in for
# a scanner's failure modes without the network or the real toolchain.
STUB="$TMP/stubbin"; mkdir -p "$STUB"
cat > "$STUB/cargo-audit" <<'STUBEOF'
#!/bin/sh
echo "Crate: fakecrate  ID: RUSTSEC-0000-0000"
exit 7
STUBEOF
cat > "$STUB/npm" <<'STUBEOF'
#!/bin/sh
case "$1" in
  audit) printf '{\n  "error": {\n    "code": "ENOLOCK",\n    "summary": "This command requires an existing lockfile."\n  }\n}\n'; exit 1 ;;
  *) echo '{}'; exit 0 ;;
esac
STUBEOF
chmod +x "$STUB/cargo-audit" "$STUB/npm"
# A GNU-style timeout (exit 124 on expiry) for hosts without one, and a docker
# that answers instantly or, with DOCKER_STUB_HANG set, never.
TSTUB="$TMP/timeoutbin"; mkdir -p "$TSTUB"
cat > "$TSTUB/timeout" <<'STUBEOF'
#!/bin/bash
s=$1; shift
# The watcher leaves a mark before it kills, so expiry is decided by the mark and
# not by whether the watcher is still alive — that raced under load.
mark="${TMPDIR:-/tmp}/timeout-stub.$$"; rm -f "$mark"
"$@" & p=$!
( trap 'kill $sp 2>/dev/null; exit 0' TERM; sleep "$s" & sp=$!; wait $sp; : > "$mark"; kill -TERM "$p" 2>/dev/null ) & w=$!
if wait "$p"; then rc=0; else rc=$?; fi
kill -TERM "$w" 2>/dev/null; wait "$w" 2>/dev/null
if [ -e "$mark" ]; then rm -f "$mark"; exit 124; fi
exit "$rc"
STUBEOF
cat > "$STUB/docker" <<'STUBEOF'
#!/bin/sh
[ -z "${DOCKER_STUB_HANG:-}" ] || exec sleep 5
case "$1" in
  ps) [ -z "${DOCKER_STUB_PSFAIL:-}" ] || { echo "Cannot connect to the Docker daemon" >&2; exit 1; }
      [ -z "${DOCKER_STUB_PSWARN:-}" ] || echo "WARNING: stub warning" >&2
      [ -n "${DOCKER_STUB_NONE:-}" ] || echo c1 ;;
  exec) [ -z "${DOCKER_STUB_EXECFAIL:-}" ] || { echo "Error response from daemon: permission denied" >&2; exit 126; }
        case "$3" in true) exit 0 ;; sh) case "$*" in *mariadb*) echo mariadb ;; esac ;; *) exit 1 ;; esac ;;
esac
STUBEOF
chmod +x "$TSTUB/timeout" "$STUB/docker"

echo "probe.sh classification tests"
echo

# --- exit codes -------------------------------------------------------------
echo "usage and exit codes"
bash "$PROBE" >/dev/null 2>&1; [ $? -eq 2 ] && ok "no args exits 2" || bad "no args exits 2" 2 "$?"
bash "$PROBE" "$TMP/nope" >/dev/null 2>&1; [ $? -eq 2 ] && ok "missing target exits 2" || bad "missing target exits 2" 2 "$?"
touch "$TMP/afile"
bash "$PROBE" "$TMP/afile" >/dev/null 2>&1; [ $? -eq 2 ] && ok "file target exits 2" || bad "file target exits 2" 2 "$?"
mkdir -p "$TMP/plain"
bash "$PROBE" "$TMP/plain" -o "$TMP/b0" >/dev/null 2>&1; [ $? -eq 0 ] && ok "empty dir exits 0" || bad "empty dir exits 0" 0 "$?"

# --- the core contract ------------------------------------------------------
echo
echo "status classification"
M=$(run "$TMP/plain")
[ -z "$(awk -F'\t' '$3=="error"' "$M")" ] \
  && ok "empty target produces zero error rows" \
  || bad "empty target produces zero error rows" "none" "$(awk -F'\t' '$3=="error" {print $1}' "$M" | tr '\n' ' ')"

# A grep that matches nothing is a RESULT. v1.0.0 masked this with `|| true`,
# which also made real failures unreportable.
[ "$(status_of "$M" secret-scan)" = "empty" ] \
  && ok "no-match grep classifies as empty, not error" \
  || bad "no-match grep classifies as empty" empty "$(status_of "$M" secret-scan)"

mkdir -p "$TMP/sec"; printf 'api_key: 9f8a7b6c5d4e3f21\n' > "$TMP/sec/conf.yml"
M=$(run "$TMP/sec")
[ "$(status_of "$M" secret-scan)" = "ok" ] \
  && ok "matching grep classifies as ok" \
  || bad "matching grep classifies as ok" ok "$(status_of "$M" secret-scan)"
F="$(dirname "$M")/out/secret-scan.txt"
[ "$(field "$M" secret-scan 5)" = "$(wc -c < "$F" | tr -d ' ')" ] && [ "$(field "$M" secret-scan 6)" = "$(wc -l < "$F" | tr -d ' ')" ] && [ "$(field "$M" secret-scan 4)" = "0" ] \
  && ok "exit, bytes and lines columns match the probe and its file" \
  || bad "exit, bytes and lines columns match the probe and its file" "exit 0, bytes $(wc -c < "$F" | tr -d ' '), lines $(wc -l < "$F" | tr -d ' ')" "exit $(field "$M" secret-scan 4), bytes $(field "$M" secret-scan 5), lines $(field "$M" secret-scan 6)"

# Placeholders must not be reported as secrets, or every result is noise.
mkdir -p "$TMP/ph"; printf 'password: changeme\napi_key: your_key_here\ntoken: ${FROM_ENV}\n' > "$TMP/ph/conf.yml"
M=$(run "$TMP/ph")
[ "$(status_of "$M" secret-scan)" = "empty" ] \
  && ok "placeholder values are filtered out" \
  || bad "placeholder values are filtered out" empty "$(status_of "$M" secret-scan)"

# --- unreadable input must never read as clean ------------------------------
echo
echo "unreadable input"
if [ "$ROOT" -eq 0 ]; then
  mkdir -p "$TMP/perm/open" "$TMP/perm/shut"
  printf 'token: aaaaaaaaaaaa\n' > "$TMP/perm/shut/x.yml"
  chmod 000 "$TMP/perm/shut"
  M=$(run "$TMP/perm")
  chmod 755 "$TMP/perm/shut"
  [ "$(field "$M" secret-scan 7)" = "yes" ] \
    && ok "unreadable subtree is flagged via stderr column" \
    || bad "unreadable subtree is flagged via stderr column" yes "$(field "$M" secret-scan 7)"
  case "$(note_of "$M" secret-scan)" in
    *"stderr present"*) ok "note names the stderr file" ;;
    *) bad "note names the stderr file" "mentions stderr" "$(note_of "$M" secret-scan)" ;;
  esac
  [ -s "$(dirname "$M")/out/secret-scan.err" ] \
    && ok "the stderr file the note names exists" \
    || bad "the stderr file the note names exists" "non-empty out/secret-scan.err" "missing"
  grep -q 'WARN .* wrote stderr' "$(dirname "$M")/summary.txt" \
    && ok "the summary warns that probes wrote stderr" \
    || bad "the summary warns that probes wrote stderr" "WARN … wrote stderr" "$(tr '\n' '|' < "$(dirname "$M")/summary.txt")"
else
  skipped "unreadable-input tests — root reads everything"
fi

# --- scope: the host is not the target --------------------------------------
echo
echo "scope containment"
mkdir -p "$TMP/dock"; touch "$TMP/dock/Dockerfile"
M=$(run "$TMP/dock")
[ "$(status_of "$M" docker-ps)" = "n/a" ] \
  && ok "host containers are not inspected by default" \
  || bad "host containers are not inspected by default" n/a "$(status_of "$M" docker-ps)"

# --- truncation must be visible ---------------------------------------------
echo
echo "truncation"
# lang-census caps at 20 lines. 25 distinct extensions must be flagged. v1.2.0's
# assertion had an `||` limb its own fixture always satisfied, so deleting the
# TRUNCATED block left it green.
mkdir -p "$TMP/many"
for e in a b c d e f g h i j k l m n o p q r s t u v w x y; do printf 'x\n' > "$TMP/many/f.x$e"; done
M=$(run "$TMP/many")
case "$(note_of "$M" lang-census)" in
  TRUNCATED*) ok "output over the line cap is flagged TRUNCATED" ;;
  *) bad "output over the line cap is flagged TRUNCATED" "note starting TRUNCATED" "$(note_of "$M" lang-census)" ;;
esac
FULL="$(dirname "$M")/out/lang-census.full.txt"
[ "$(wc -l < "$(dirname "$M")/out/lang-census.txt" | tr -d ' ')" = "20" ] \
  && ok "the capped file holds exactly the cap" \
  || bad "the capped file holds exactly the cap" 20 "$(wc -l < "$(dirname "$M")/out/lang-census.txt")"
case "$(note_of "$M" lang-census)" in
  "TRUNCATED: 20 of 25 lines"*) ok "the TRUNCATED note states the cap and the population" ;;
  *) bad "the TRUNCATED note states the cap and the population" "TRUNCATED: 20 of 25 lines…" "$(note_of "$M" lang-census)" ;;
esac
[ "$(wc -l < "$FULL" 2>/dev/null | tr -d ' ')" = "25" ] \
  && ok "the complete output is kept beside the capped file" \
  || bad "the complete output is kept beside the capped file" "25 lines in lang-census.full.txt" "$(wc -l < "$FULL" 2>/dev/null)"
# Exactly at the cap is complete. v1.2.x flagged it, because head cannot say
# whether anything followed.
mkdir -p "$TMP/atcap"
for e in a b c d e f g h i j k l m n o p q r s t; do printf 'x\n' > "$TMP/atcap/f.x$e"; done
M=$(run "$TMP/atcap")
case "$(note_of "$M" lang-census)" in
  TRUNCATED*) bad "output exactly at the cap is not flagged" "no TRUNCATED" "$(note_of "$M" lang-census)" ;;
  *) ok "output exactly at the cap is not flagged" ;;
esac
mkdir -p "$TMP/few"; printf 'x\n' > "$TMP/few/a.xa"; printf 'x\n' > "$TMP/few/b.xb"
M=$(run "$TMP/few")
case "$(note_of "$M" lang-census)" in
  TRUNCATED*) bad "output under the cap is not flagged" "no TRUNCATED" "$(note_of "$M" lang-census)" ;;
  *) ok "output under the cap is not flagged" ;;
esac
[ -z "$(ls "$(dirname "$M")"/out/*.full.txt 2>/dev/null)" ] \
  && ok "no .full.txt is left for output under its cap" \
  || bad "no .full.txt is left for output under its cap" none "$(ls "$(dirname "$M")"/out/*.full.txt)"

# --- awkward paths ----------------------------------------------------------
echo
echo "awkward targets"
mkdir -p "$TMP/has space/sub" && printf 'x\n' > "$TMP/has space/sub/a.txt"
bash "$PROBE" "$TMP/has space" -o "$TMP/b-space" >/dev/null 2>&1
[ $? -eq 0 ] && ok "path containing a space" || bad "path containing a space" 0 "$?"
ln -s "$TMP/has space" "$TMP/link"
bash "$PROBE" "$TMP/link" -o "$TMP/b-link" >/dev/null 2>&1
[ $? -eq 0 ] && ok "symlinked target" || bad "symlinked target" 0 "$?"
mkdir -p "$TMP/q/a\$b'c \"d\""
bash "$PROBE" "$TMP/q" -o "$TMP/b-q" >/dev/null 2>&1
[ $? -eq 0 ] && ok "shell metacharacters in a child path" || bad "shell metacharacters in a child path" 0 "$?"

# --- bundle hygiene ---------------------------------------------------------
echo
echo "bundle hygiene"
# The second target has no package.json, so npm-manifest never runs on it. Only
# clearing out/ can remove the first run's copy. v1.2.0 checked secret-scan.txt,
# which probe() rewrites with `>` either way, so removing the clear left it green.
mkdir -p "$TMP/r1" "$TMP/r2"; printf '{"name":"first-target"}\n' > "$TMP/r1/package.json"
PATH="$STUB:$PATH" bash "$PROBE" "$TMP/r1" -o "$TMP/b-reuse" >/dev/null 2>&1
[ -s "$TMP/b-reuse/out/npm-manifest.txt" ] \
  && ok "fixture: first run wrote npm-manifest.txt" \
  || bad "fixture: first run wrote npm-manifest.txt" "non-empty file" "missing"
bash "$PROBE" "$TMP/r2" -o "$TMP/b-reuse" >/dev/null 2>&1
[ ! -e "$TMP/b-reuse/out/npm-manifest.txt" ] \
  && ok "a reused bundle does not retain the previous target's evidence" \
  || bad "a reused bundle does not retain the previous target's evidence" "no out/npm-manifest.txt" "$(head -c 60 "$TMP/b-reuse/out/npm-manifest.txt")"

# 1.3.0 added .full.txt and .err files; reuse must clear those too.
mkdir -p "$TMP/many-dock"; cp "$TMP/many"/* "$TMP/many-dock/"; : > "$TMP/many-dock/Dockerfile"
DOCKER_STUB_PSWARN=1 PATH="$STUB:$PATH" bash "$PROBE" "$TMP/many-dock" --host-containers -o "$TMP/b-reuse2" >/dev/null 2>&1
[ -n "$(ls "$TMP/b-reuse2"/out/*.full.txt 2>/dev/null)" ] && [ -n "$(ls "$TMP/b-reuse2"/out/*.err 2>/dev/null)" ] \
  && ok "fixture: first run wrote a .full.txt and an .err" \
  || bad "fixture: first run wrote a .full.txt and an .err" "both" "$(ls "$TMP/b-reuse2/out" 2>/dev/null | tr '\n' ' ')"
bash "$PROBE" "$TMP/plain" -o "$TMP/b-reuse2" >/dev/null 2>&1
[ -e "$TMP/b-reuse2/manifest.tsv" ] && [ -z "$(ls "$TMP/b-reuse2"/out/*.full.txt "$TMP/b-reuse2"/out/*.err 2>/dev/null)" ] \
  && ok "a reused bundle does not retain the previous run's .full.txt or .err" \
  || bad "a reused bundle does not retain the previous run's .full.txt or .err" none "$(ls "$TMP/b-reuse2"/out/*.full.txt "$TMP/b-reuse2"/out/*.err 2>/dev/null | tr '\n' ' ')"

# -o must never clear a directory probe.sh did not create. v1.2.0 ran rm -rf on
# any out/ it found.
mkdir -p "$TMP/victim/out"; printf 'keep me\n' > "$TMP/victim/out/user-data.txt"
bash "$PROBE" "$TMP/plain" -o "$TMP/victim" >/dev/null 2>&1; RC=$?
[ "$RC" -eq 2 ] && [ -f "$TMP/victim/out/user-data.txt" ] \
  && ok "an unmarked non-empty -o directory is refused and left intact" \
  || bad "an unmarked non-empty -o directory is refused and left intact" "exit 2, file kept" "exit $RC, file $([ -f "$TMP/victim/out/user-data.txt" ] && echo kept || echo GONE)"
# A project root has no out/ of its own, and must be refused just the same.
mkdir -p "$TMP/victim2"; printf 'notes\n' > "$TMP/victim2/notes.txt"
bash "$PROBE" "$TMP/plain" -o "$TMP/victim2" >/dev/null 2>&1; RC=$?
[ "$RC" -eq 2 ] && [ ! -e "$TMP/victim2/manifest.tsv" ] \
  && ok "an unmarked non-empty -o directory with no out/ is refused" \
  || bad "an unmarked non-empty -o directory with no out/ is refused" "exit 2, nothing written" "exit $RC"
bash "$PROBE" "$TMP/plain" -o "$TMP/afile" >/dev/null 2>&1; RC=$?
[ "$RC" -eq 2 ] && [ ! -s "$TMP/afile" ] \
  && ok "-o naming a regular file is refused" \
  || bad "-o naming a regular file is refused" "exit 2, file untouched" "exit $RC"
# An existing empty directory the caller owns is made private before use.
mkdir -p "$TMP/openbundle"; chmod 755 "$TMP/openbundle"
bash "$PROBE" "$TMP/plain" -o "$TMP/openbundle" >/dev/null 2>&1
case "$(ls -ld "$TMP/openbundle")" in
  drwx------*) ok "an existing -o directory is made private" ;;
  *) bad "an existing -o directory is made private" drwx------ "$(ls -ld "$TMP/openbundle")" ;;
esac

# v1.2.0 interpolated --timeout into eval; anything but digits must still be
# rejected before a single probe runs.
PWN="$TMP/pwned"
bash "$PROBE" "$TMP/plain" -o "$TMP/b-inj" --timeout "1; touch $PWN" >/dev/null 2>&1; RC=$?
[ "$RC" -eq 2 ] && [ ! -e "$PWN" ] && [ ! -e "$TMP/b-inj" ] \
  && ok "a non-numeric --timeout is rejected before anything runs" \
  || bad "a non-numeric --timeout is rejected before anything runs" "exit 2, nothing created" "exit $RC, pwned=$([ -e "$PWN" ] && echo yes || echo no), bundle=$([ -e "$TMP/b-inj" ] && echo yes || echo no)"
bash "$PROBE" "$TMP/plain" -o "$TMP/b-emptyt" --timeout '' >/dev/null 2>&1; RC=$?
[ "$RC" -eq 2 ] && [ ! -e "$TMP/b-emptyt" ] \
  && ok "an empty --timeout is rejected" \
  || bad "an empty --timeout is rejected" "exit 2" "exit $RC"

M="$TMP/b-reuse/manifest.tsv"
[ "$(head -1 "$M" | awk -F'\t' '{print NF}')" -eq 9 ] \
  && ok "manifest header has all 9 columns" \
  || bad "manifest header has all 9 columns" 9 "$(head -1 "$M" | awk -F'\t' '{print NF}')"

BAD=$(awk -F'\t' 'NR>1 && NF!=9 {print $1}' "$M" | tr '\n' ' ')
[ -z "$BAD" ] && ok "every manifest row has 9 columns" || bad "every manifest row has 9 columns" "all 9" "$BAD"

# --- the statuses a clean fixture never reaches -----------------------------
# Every fixture above runs tools that succeed, so none of them can tell `error`
# from `empty` or `output` from `error`. These build probes that fail on purpose.
echo
echo "failure statuses"

mkdir -p "$TMP/crate"; printf '[package]\nname = "x"\n' > "$TMP/crate/Cargo.toml"
M=$(PATH="$STUB:$PATH" run "$TMP/crate" --run-toolchains)
[ "$(status_of "$M" cargo-audit)" = "output" ] \
  && ok "nonzero exit outside ok_exits WITH stdout classifies as output" \
  || bad "nonzero exit outside ok_exits WITH stdout classifies as output" output "$(status_of "$M" cargo-audit)"

# npm audit exits 1 both when it finds vulnerabilities and when it cannot audit.
mkdir -p "$TMP/nolock"; printf '{"name":"x","version":"1.0.0"}\n' > "$TMP/nolock/package.json"
M=$(PATH="$STUB:$PATH" run "$TMP/nolock" --run-toolchains)
[ "$(status_of "$M" npm-audit)" = "error" ] \
  && ok "npm audit reporting ENOLOCK classifies as error, not ok" \
  || bad "npm audit reporting ENOLOCK classifies as error, not ok" error "$(status_of "$M" npm-audit)"

if command -v git >/dev/null 2>&1; then
  # A repo with no commits: git rev-list --count HEAD exits 128 with no stdout.
  mkdir -p "$TMP/nocommit"; ( cd "$TMP/nocommit" && git init -q ) >/dev/null 2>&1
  M=$(run "$TMP/nocommit")
  [ "$(status_of "$M" git-commit-count)" = "error" ] \
    && ok "a probe that could not run classifies as error, not empty" \
    || bad "a probe that could not run classifies as error, not empty" error "$(status_of "$M" git-commit-count)"
  [ "$(field "$M" git-commit-count 4)" = "128" ] \
    && ok "the exit column holds the command's own exit" \
    || bad "the exit column holds the command's own exit" 128 "$(field "$M" git-commit-count 4)"
  case "$(note_of "$M" git-commit-count)" in
    *fatal*) ok "an error note quotes the command's stderr" ;;
    *) bad "an error note quotes the command's stderr" "…fatal…" "$(note_of "$M" git-commit-count)" ;;
  esac
else
  skipped "error-status test — git not installed"
fi

# --- testing axis -----------------------------------------------------------
echo
echo "test discovery"
mkdir -p "$TMP/shtests"; : > "$TMP/shtests/test_one.sh"; : > "$TMP/shtests/two_test.sh"
M=$(run "$TMP/shtests")
[ "$(cat "$(dirname "$M")/out/test-file-count.txt")" = "2" ] \
  && ok "shell test files are counted" \
  || bad "shell test files are counted" 2 "$(cat "$(dirname "$M")/out/test-file-count.txt")"
mkdir -p "$TMP/testnames/test" "$TMP/testnames/tests" "$TMP/testnames/spec" "$TMP/testnames/__tests__"
for f in a_test.php b_test.go c.test.js d.test.ts test_e.py f_spec.rb test_g.sh h_test.sh; do : > "$TMP/testnames/$f"; done
: > "$TMP/testnames/test_new
line.sh"
M=$(run "$TMP/testnames"); OUT="$(dirname "$M")/out"
[ "$(cat "$OUT/test-file-count.txt")" = "9" ] \
  && ok "every documented test-file convention is counted, once per file" \
  || bad "every documented test-file convention is counted, once per file" 9 "$(cat "$OUT/test-file-count.txt")"
[ "$(wc -l < "$OUT/test-inventory.txt" | tr -d ' ')" = "4" ] \
  && ok "test, tests, spec and __tests__ directories are inventoried" \
  || bad "test, tests, spec and __tests__ directories are inventoried" 4 "$(tr '\n' ' ' < "$OUT/test-inventory.txt")"

# --- exit status carries the producer's failure ----------------------------
# v1.2.x ended most commands in `| head`, so the exit column was head's and a
# find that could not read the tree reported 0 and `empty`.
echo
echo "exit status and unreadable targets"
if [ "$ROOT" -eq 0 ]; then
  mkdir -p "$TMP/perm2/shut"; : > "$TMP/perm2/shut/Dockerfile"; : > "$TMP/perm2/shut/a.js"
  chmod 000 "$TMP/perm2/shut"
  M=$(run "$TMP/perm2")
  chmod 755 "$TMP/perm2/shut"
  for p in dockerfiles lang-census; do
    [ "$(status_of "$M" $p)" = "error" ] \
      && ok "$p on an unreadable subtree is error" \
      || bad "$p on an unreadable subtree is error" error "$(status_of "$M" $p) (exit $(field "$M" $p 4))"
  done
  # A target that can be entered but not listed. `ls LICENSE* 2>/dev/null` reported
  # every name absent and filed empty.
  mkdir -p "$TMP/xonly"; : > "$TMP/xonly/LICENSE"; : > "$TMP/xonly/.editorconfig"
  chmod 100 "$TMP/xonly"
  M=$(run "$TMP/xonly")
  chmod 755 "$TMP/xonly"
  for p in lint-config ci-config license-files; do
    [ "$(status_of "$M" $p)" = "error" ] \
      && ok "$p on an unlistable target is error, not empty" \
      || bad "$p on an unlistable target is error, not empty" error "$(status_of "$M" $p)"
  done
  # bash -n exits 126 on a file it cannot read. That is not a syntax result.
  if ! command -v shellcheck >/dev/null 2>&1; then
    mkdir -p "$TMP/shunread"; printf 'echo ok\n' > "$TMP/shunread/a.sh"; chmod 000 "$TMP/shunread/a.sh"
    M=$(run "$TMP/shunread"); chmod 644 "$TMP/shunread/a.sh"
    [ "$(status_of "$M" shell-syntax-only)" = "output" ] \
      && ok "bash -n unable to read a file is output, not ok" \
      || bad "bash -n unable to read a file is output, not ok" output "$(status_of "$M" shell-syntax-only)"
  else
    skipped "unreadable bash -n test — shellcheck is installed, so shell-syntax-only does not run"
  fi
else
  skipped "unreadable-target tests — root reads everything"
fi

# Checkers report findings as a nonzero exit. v1.3.0 ran them through xargs,
# which BSD passes on as 1 where GNU uses 123. Both must read as results.
mkdir -p "$TMP/checkers"; printf 'FROM alpine:3.19\n' > "$TMP/checkers/Dockerfile"; printf 'if then\n' > "$TMP/checkers/bad.sh"
M=$(run "$TMP/checkers")
[ "$(status_of "$M" dockerfile-fetches)" = "empty" ] \
  && ok "a Dockerfile with no fetches is empty, not error" \
  || bad "a Dockerfile with no fetches is empty, not error" empty "$(status_of "$M" dockerfile-fetches) (exit $(field "$M" dockerfile-fetches 4))"
if command -v shellcheck >/dev/null 2>&1; then SP=shell-lint; else SP=shell-syntax-only; fi
[ "$(status_of "$M" $SP)" = "ok" ] \
  && ok "a shell syntax error found by $SP is ok, not error" \
  || bad "a shell syntax error found by $SP is ok, not error" ok "$(status_of "$M" $SP) (exit $(field "$M" $SP 4))"
# php and shellcheck, stubbed with their real exit conventions: php -l 255 on a
# parse error, shellcheck 1 on findings and 2+ when it could not check a file.
CSTUB="$TMP/checkerbin"; mkdir -p "$CSTUB"
cat > "$CSTUB/php" <<'STUBEOF'
#!/bin/sh
[ "$1" = "-l" ] || exit 64
case "$2" in *unopenable*) echo "Could not open input file: $2"; exit 1 ;; esac
if grep -q ';' "$2"; then echo "No syntax errors detected in $2"; exit 0; fi
echo "PHP Parse error: syntax error in $2 on line 1"; exit 255
STUBEOF
cat > "$CSTUB/shellcheck" <<'STUBEOF'
#!/bin/sh
shift 2
rc=0
for f; do case "$f" in
  *bad.sh) echo "$f:1:1: warning: stub finding [SC0000]"; [ $rc -ge 1 ] || rc=1 ;;
  *unreadable*) echo "$f: cannot read" >&2; rc=2 ;;
esac; done
exit $rc
STUBEOF
chmod +x "$CSTUB/php" "$CSTUB/shellcheck"
printf '{}\n' > "$TMP/checkers/composer.json"; printf '<?php echo 1\n' > "$TMP/checkers/bad.php"; printf '<?php echo 1;\n' > "$TMP/checkers/good.php"
M=$(PATH="$CSTUB:$PATH" run "$TMP/checkers")
OUT="$(dirname "$M")/out"
[ "$(status_of "$M" php-syntax)" = "ok" ] && grep -q 'bad.php' "$OUT/php-syntax.txt" && ! grep -q 'No syntax errors' "$OUT/php-syntax.txt" \
  && ok "a php parse error is ok, listed, and clean files are filtered out" \
  || bad "a php parse error is ok, listed, and clean files are filtered out" "ok, bad.php only" "$(status_of "$M" php-syntax): $(tr '\n' ' ' < "$OUT/php-syntax.txt" 2>/dev/null)"
[ "$(status_of "$M" shell-lint)" = "ok" ] \
  && ok "shellcheck findings are ok, not error" \
  || bad "shellcheck findings are ok, not error" ok "$(status_of "$M" shell-lint) (exit $(field "$M" shell-lint 4))"
: > "$TMP/checkers/unreadable.sh"
M=$(PATH="$CSTUB:$PATH" run "$TMP/checkers")
[ "$(status_of "$M" shell-lint)" = "output" ] \
  && ok "shellcheck unable to check a file is output, not ok" \
  || bad "shellcheck unable to check a file is output, not ok" output "$(status_of "$M" shell-lint)"
# php -l exits 1 when it cannot open a file. That is not a parse result.
printf '<?php echo 1;\n' > "$TMP/checkers/unopenable.php"
M=$(PATH="$CSTUB:$PATH" run "$TMP/checkers")
[ "$(status_of "$M" php-syntax)" = "output" ] \
  && ok "php unable to open a file is output, not ok" \
  || bad "php unable to open a file is output, not ok" output "$(status_of "$M" php-syntax)"
rm -f "$TMP/checkers/unopenable.php"
# php -l is one process per file. Serially, 4,607 files ran past a 120-second cap.
# Eight files at one second each must finish inside five seconds.
SPHP="$TMP/slowphp"; mkdir -p "$SPHP" "$TMP/manyphp"
printf '#!/bin/sh\nsleep 1\necho "No syntax errors detected in $2"\n' > "$SPHP/php"; chmod +x "$SPHP/php"
printf '{}\n' > "$TMP/manyphp/composer.json"
for i in 1 2 3 4 5 6 7 8; do printf '<?php echo %s;\n' $i > "$TMP/manyphp/f$i.php"; done
M=$(PATH="$SPHP:$TSTUB:$PATH" run "$TMP/manyphp" --timeout 5)
[ "$(status_of "$M" php-syntax)" = "empty" ] \
  && ok "php-syntax checks files in parallel, inside the timeout" \
  || bad "php-syntax checks files in parallel, inside the timeout" "empty" "$(status_of "$M" php-syntax): $(note_of "$M" php-syntax)"
# Filenames reach php through xargs. None may be split, unquoted or run as shell:
# each must arrive as one argument naming a file that exists.
HPHP="$TMP/hostilephp"; mkdir -p "$HPHP" "$TMP/hostnames"
cat > "$HPHP/php" <<'STUBEOF'
#!/bin/sh
if [ -f "$2" ]; then echo intact >> "$PHPLOG"; else echo "broken: $2" >> "$PHPLOG"; fi
echo "No syntax errors detected in $2"
STUBEOF
chmod +x "$HPHP/php"; printf '{}\n' > "$TMP/hostnames/composer.json"
for n in 'sp ace.php' "q'uote.php" 'd"q.php' 'back\slash.php' '$(touch pwned-subst).php' ';touch pwned-semi;.php' '-dash.php' '*.php' '`touch pwned-tick`.php'; do
  printf '<?php echo 1;\n' > "$TMP/hostnames/$n"
done
printf '<?php echo 1;\n' > "$TMP/hostnames/new
line.php"
PHPLOG="$TMP/phplog"; : > "$PHPLOG"; export PHPLOG
M=$(PATH="$HPHP:$PATH" run "$TMP/hostnames")
INTACT=$(grep -c '^intact$' "$PHPLOG"); BROKEN=$(grep -v '^intact$' "$PHPLOG" | tr '\n' '|')
# A name holding a newline still splits php's own one-line message in two, so the
# row can read ok with a stray line; that is display, not an escape.
RAN=""; for f in pwned-subst pwned-semi pwned-tick; do [ ! -e "$TMP/hostnames/$f" ] || RAN="$RAN $f"; done
case "$(status_of "$M" php-syntax)" in ok|empty) ST=fine ;; *) ST="$(status_of "$M" php-syntax)" ;; esac
[ "$INTACT" = "10" ] && [ -z "$BROKEN" ] && [ -z "$RAN" ] && [ "$ST" = fine ] \
  && ok "hostile php filenames reach php -l whole, once each, and run nothing" \
  || bad "hostile php filenames reach php -l whole, once each, and run nothing" "10 intact, 0 broken, nothing run, ok or empty" "$INTACT intact; broken: $BROKEN; ran:$RAN; status $ST"
unset PHPLOG
grep -q '^checker jobs: *[0-9][0-9]*$' "$(dirname "$M")/env.txt" \
  && ok "env.txt records how many checker processes ran at once" \
  || bad "env.txt records how many checker processes ran at once" "checker jobs: N" "$(grep '^checker' "$(dirname "$M")/env.txt")"

# --- pruning and awkward names in the size probes ---------------------------
echo
echo "pruning and file names"
mkdir -p "$TMP/mono/pkgs/a/node_modules/junk" "$TMP/mono/src"
printf 'real\n' > "$TMP/mono/src/app.js"
i=0; while [ $i -lt 20 ]; do printf '%0200d\n' 0 > "$TMP/mono/pkgs/a/node_modules/junk/j$i.js"; i=$((i+1)); done
M=$(run "$TMP/mono")
OUT="$(dirname "$M")/out"
[ "$(cat "$OUT/file-count.txt")" = "1" ] \
  && ok "nested node_modules are pruned from file-count" \
  || bad "nested node_modules are pruned from file-count" 1 "$(cat "$OUT/file-count.txt")"
grep -q node_modules "$OUT/largest-files.txt" \
  && bad "nested node_modules are pruned from largest-files" "no node_modules paths" "$(head -1 "$OUT/largest-files.txt")" \
  || ok "nested node_modules are pruned from largest-files"

mkdir -p "$TMP/names/sp ace"
printf '%01000d\n' 0 > "$TMP/names/sp ace/big file.txt"
: > "$TMP/names/new
line.txt"
M=$(run "$TMP/names")
OUT="$(dirname "$M")/out"
head -1 "$OUT/largest-files.txt" | grep -q '\./sp ace/big file\.txt$' \
  && ok "largest-files keeps a path containing spaces whole" \
  || bad "largest-files keeps a path containing spaces whole" "./sp ace/big file.txt" "$(head -1 "$OUT/largest-files.txt")"
[ "$(cat "$OUT/file-count.txt")" = "2" ] \
  && ok "a filename containing a newline counts once" \
  || bad "a filename containing a newline counts once" 2 "$(cat "$OUT/file-count.txt")"

# --- secret-scan coverage ---------------------------------------------------
echo
echo "secret-scan coverage"
mkdir -p "$TMP/langs"
for f in s.tsx s.jsx s.vue s.java s.kt s.cs s.rs s.swift s.c s.cpp s.md Dockerfile Makefile; do
  printf 'api_key = "AKIA1234567890ABCD"\n' > "$TMP/langs/$f"
done
# Run from a directory holding decoys: an unquoted glob in probe.sh expands
# against the caller's cwd, and did — `*.md` became `CLAUDE.md`.
mkdir -p "$TMP/decoycwd"; : > "$TMP/decoycwd/CLAUDE.md"; : > "$TMP/decoycwd/x.tsx"; : > "$TMP/decoycwd/Makefile.bak"
M=$(cd "$TMP/decoycwd" && run "$TMP/langs")
N=$(wc -l < "$(dirname "$M")/out/secret-scan.txt" | tr -d ' ')
[ "$N" = "13" ] \
  && ok "the 13 file types v1.2.0 skipped are scanned" \
  || bad "the 13 file types v1.2.0 skipped are scanned" 13 "$N: $(cut -d: -f1 "$(dirname "$M")/out/secret-scan.txt" | tr '\n' ' ')"
M=$(run "$TMP/plain")
case "$(note_of "$M" secret-scan)" in
  *"not evidence of no secrets"*) ok "an empty secret-scan says what it did not read" ;;
  *) bad "an empty secret-scan says what it did not read" "coverage caveat" "$(note_of "$M" secret-scan)" ;;
esac
grep -q '^secret-scan reads: .*\*\.tsx' "$(dirname "$M")/env.txt" \
  && ok "env.txt lists the file types secret-scan read" \
  || bad "env.txt lists the file types secret-scan read" "secret-scan reads: …" "missing"

# --- timeouts ---------------------------------------------------------------
echo
echo "timeouts"
if ! command -v timeout >/dev/null 2>&1 && ! command -v gtimeout >/dev/null 2>&1; then
  M=$(run "$TMP/plain")
  grep -q '^timeout: *NONE ENFORCED' "$(dirname "$M")/env.txt" \
    && ok "env.txt says no timeout was enforced when no binary exists" \
    || bad "env.txt says no timeout was enforced when no binary exists" "NONE ENFORCED" "$(grep '^timeout' "$(dirname "$M")/env.txt")"
  grep -q 'WARN .*no timeout binary' "$(dirname "$M")/summary.txt" \
    && ok "the summary warns that probes ran unbounded" \
    || bad "the summary warns that probes ran unbounded" "WARN no timeout binary" "$(tr '\n' '|' < "$(dirname "$M")/summary.txt")"
else
  skipped "no-binary env.txt test — this host has a timeout binary"
fi
M=$(PATH="$TSTUB:$PATH" run "$TMP/plain" --timeout 0)
grep -q '^timeout: *none — disabled' "$(dirname "$M")/env.txt" \
  && ok "--timeout 0 applies no timeout even where a binary exists" \
  || bad "--timeout 0 applies no timeout even where a binary exists" "none — disabled" "$(grep '^timeout' "$(dirname "$M")/env.txt")"
if ! command -v timeout >/dev/null 2>&1; then
  GT="$TMP/gtimeoutbin"; mkdir -p "$GT"; ln -s "$TSTUB/timeout" "$GT/gtimeout"
  M=$(PATH="$GT:$PATH" run "$TMP/plain" --timeout 30)
  grep -q '^timeout: *30s per probe, enforced by gtimeout' "$(dirname "$M")/env.txt" \
    && ok "gtimeout is used where timeout is absent" \
    || bad "gtimeout is used where timeout is absent" "enforced by gtimeout" "$(grep '^timeout' "$(dirname "$M")/env.txt")"
else
  skipped "gtimeout detection test — this host has timeout"
fi
M=$(PATH="$TSTUB:$STUB:$PATH" run "$TMP/dock" --host-containers --timeout 30)
grep -q '^timeout: *30s per probe, enforced by timeout' "$(dirname "$M")/env.txt" \
  && ok "env.txt names the timeout that was enforced" \
  || bad "env.txt names the timeout that was enforced" "30s … enforced by timeout" "$(grep '^timeout' "$(dirname "$M")/env.txt")"
# v1.2.0 prefixed `timeout N` to the command string: `timeout 30 for c in …` is a
# syntax error, filed as empty.
[ "$(status_of "$M" db-clients)" = "ok" ] && [ "$(field "$M" db-clients 7)" = "no" ] \
  && ok "a compound command runs under a timeout" \
  || bad "a compound command runs under a timeout" "ok, no stderr" "$(status_of "$M" db-clients), stderr=$(field "$M" db-clients 7)"
M=$(DOCKER_STUB_HANG=1 PATH="$TSTUB:$STUB:$PATH" run "$TMP/dock" --host-containers --timeout 1)
case "$(status_of "$M" docker-ps) $(note_of "$M" docker-ps)" in
  "error TIMED OUT"*) ok "a probe killed by the timeout is error, and says so" ;;
  *) bad "a probe killed by the timeout is error, and says so" "error TIMED OUT…" "$(status_of "$M" docker-ps) $(note_of "$M" docker-ps)" ;;
esac

# --- usage ------------------------------------------------------------------
echo
echo "usage"
H=$(bash "$PROBE" --help 2>&1); RC=$?
case "$RC $H" in
  "2 probe.sh <target-dir>"*"--timeout N"*) ok "--help prints the synopsis and exits 2" ;;
  *) bad "--help prints the synopsis and exits 2" "exit 2, synopsis" "exit $RC: $(echo "$H" | head -1)" ;;
esac

# --- git scope --------------------------------------------------------------
echo
echo "git detection"
if command -v git >/dev/null 2>&1; then
  mkdir -p "$TMP/repo/nested"
  ( cd "$TMP/repo" && git init -q && git config user.email t@t && git config user.name t \
    && printf 'a\n' > f.txt && git add -A && git commit -qm init ) >/dev/null 2>&1
  M=$(run "$TMP/repo")
  [ "$(status_of "$M" git-commit-count)" = "ok" ] \
    && ok "repo root is detected as version controlled" \
    || bad "repo root is detected as version controlled" ok "$(status_of "$M" git-commit-count)"
  grep -q '^git scope: *repo root$' "$(dirname "$M")/env.txt" \
    && ok "env.txt records the target as the repo root" \
    || bad "env.txt records the target as the repo root" "git scope: repo root" "$(grep '^git scope' "$(dirname "$M")/env.txt")"
  [ "$(cat "$(dirname "$M")/out/file-count.txt")" = "1" ] \
    && ok ".git is not counted as part of the tree" \
    || bad ".git is not counted as part of the tree" 1 "$(cat "$(dirname "$M")/out/file-count.txt")"
  # A subdirectory of a work tree IS version controlled. v1.0.0 said otherwise.
  M=$(run "$TMP/repo/nested")
  [ "$(status_of "$M" git-commit-count)" != "n/a" ] \
    && ok "a subdirectory of a work tree is not reported as unversioned" \
    || bad "a subdirectory of a work tree is not reported as unversioned" "not n/a" "n/a"
  grep -q '^git scope: *subdirectory of ' "$(dirname "$M")/env.txt" \
    && ok "env.txt records a subdirectory as a subdirectory" \
    || bad "env.txt records a subdirectory as a subdirectory" "git scope: subdirectory of …" "$(grep '^git scope' "$(dirname "$M")/env.txt")"
  ( cd "$TMP/repo" && i=0 && while [ $i -lt 41 ]; do echo $i > f.txt; git commit -qam "c$i"; i=$((i+1)); done ) >/dev/null 2>&1
  M=$(run "$TMP/repo")
  case "$(note_of "$M" git-log)" in
    TRUNCATED*) ok "git-log over 40 commits says it is truncated" ;;
    *) bad "git-log over 40 commits says it is truncated" "TRUNCATED…" "$(note_of "$M" git-log)" ;;
  esac
else
  skipped "git tests — git not installed"
fi

# --- the target is untrusted ------------------------------------------------
# Toolchains honour configuration the target ships. v1.3.0 ran `cargo audit`
# through a committed alias and `git status` through a committed fsmonitor hook,
# and filed both rows clean. The stubs below leave a mark if they are invoked.
echo
echo "execution of target-supplied configuration"
MARKS="$TMP/marks"; mkdir -p "$MARKS"
XSTUB="$TMP/execbin"; mkdir -p "$XSTUB"
for t in cargo composer npm pip-audit govulncheck bundle bundler-audit; do
  printf '#!/bin/sh\necho "$* GOTOOLCHAIN=${GOTOOLCHAIN:-}" >> "%s/%s"\necho "{\\"auditReportVersion\\": 2, \\"dependencies\\": []}"\nexit 0\n' "$MARKS" "$t" > "$XSTUB/$t"
done
printf '#!/bin/sh\necho "cargo-audit argv: $*"\nexit 0\n' > "$XSTUB/cargo-audit"
chmod +x "$XSTUB"/*
mkdir -p "$TMP/hostile"
printf '[package]\nname = "x"\n' > "$TMP/hostile/Cargo.toml"
printf '{}\n' > "$TMP/hostile/composer.json"; printf '{"name":"x"}\n' > "$TMP/hostile/package.json"
printf 'django==2.2.0\n' > "$TMP/hostile/requirements.txt"; printf 'module x\n' > "$TMP/hostile/go.mod"
printf 'source "https://rubygems.org"\n' > "$TMP/hostile/Gemfile"
M=$(PATH="$XSTUB:$PATH" run "$TMP/hostile")
RAN=$(ls "$MARKS" | tr '\n' ' ')
[ -z "$RAN" ] \
  && ok "no toolchain runs without --run-toolchains" \
  || bad "no toolchain runs without --run-toolchains" "none invoked" "$RAN"
for p in composer-audit npm-audit pip-audit go-vulncheck cargo-audit bundler-audit dep-licenses; do
  case "$(status_of "$M" $p) $(note_of "$M" $p)" in
    "error not run"*) ok "$p without the flag is error, and says it was not run" ;;
    *) bad "$p without the flag is error, and says it was not run" "error not run…" "$(status_of "$M" $p) $(note_of "$M" $p)" ;;
  esac
done
grep -q '^toolchains: *NOT RUN' "$(dirname "$M")/env.txt" \
  && ok "env.txt says toolchains were not run" \
  || bad "env.txt says toolchains were not run" "toolchains: NOT RUN…" "$(grep '^toolchains' "$(dirname "$M")/env.txt")"

rm -f "$MARKS"/*
M=$(PATH="$XSTUB:$PATH" run "$TMP/hostile" --run-toolchains)
[ ! -e "$MARKS/cargo" ] && grep -q 'cargo-audit argv: audit' "$(dirname "$M")/out/cargo-audit.txt" \
  && ok "cargo-audit is invoked directly, so a cargo alias cannot resolve" \
  || bad "cargo-audit is invoked directly, so a cargo alias cannot resolve" "cargo not run, cargo-audit audit" "cargo=$(cat "$MARKS/cargo" 2>/dev/null || echo not-run), out=$(head -1 "$(dirname "$M")/out/cargo-audit.txt")"
case " $(tr '\n' ' ' < "$MARKS/govulncheck" 2>/dev/null) " in
  *" GOTOOLCHAIN=local "*) ok "govulncheck cannot switch to a toolchain the target's go.mod names" ;;
  *) bad "govulncheck cannot switch to a toolchain the target's go.mod names" "GOTOOLCHAIN=local" "$(tr '\n' ' ' < "$MARKS/govulncheck" 2>/dev/null)" ;;
esac
[ ! -e "$MARKS/bundle" ] && [ -e "$MARKS/bundler-audit" ] \
  && ok "bundler-audit is invoked directly, so bundler never evaluates the Gemfile" \
  || bad "bundler-audit is invoked directly, so bundler never evaluates the Gemfile" "bundle not run, bundler-audit run" "bundle=$([ -e "$MARKS/bundle" ] && echo run || echo not-run) bundler-audit=$([ -e "$MARKS/bundler-audit" ] && echo run || echo not-run)"
A=" $(tr '\n' ' ' < "$MARKS/composer" 2>/dev/null) "
case "$A" in *" --no-plugins "*) case "$A" in *" --no-scripts "*) A=yes ;; esac ;; esac
[ "$A" = yes ] \
  && ok "composer audit runs with --no-plugins --no-scripts" \
  || bad "composer audit runs with --no-plugins --no-scripts" "both flags" "$(tr '\n' ' ' < "$MARKS/composer" 2>/dev/null)"
case " $(tr '\n' ' ' < "$MARKS/npm" 2>/dev/null) " in
  *" --registry=https://registry.npmjs.org/ "*) ok "npm audit pins the registry, so a target .npmrc cannot redirect it" ;;
  *) bad "npm audit pins the registry, so a target .npmrc cannot redirect it" "--registry=https://registry.npmjs.org/" "$(tr '\n' ' ' < "$MARKS/npm" 2>/dev/null)" ;;
esac
# pip-audit with no arguments audits the environment it is installed in. On a
# Django 2.2 target it reported the auditor's own pip, then nothing.
A=" $(tr '\n' ' ' < "$MARKS/pip-audit" 2>/dev/null) "
case "$A" in *" -r requirements.txt "*) case "$A" in *" -f json "*) A=yes ;; esac ;; esac
case "$A" in
  yes) ok "pip-audit audits the target's requirements.txt, as JSON" ;;
  *) bad "pip-audit audits the target's requirements.txt, as JSON" "-r requirements.txt -f json" "$(tr '\n' ' ' < "$MARKS/pip-audit" 2>/dev/null)" ;;
esac
mkdir -p "$TMP/pyproj"; printf '[project]\nname = "x"\n' > "$TMP/pyproj/pyproject.toml"; rm -f "$MARKS"/*
M=$(PATH="$XSTUB:$PATH" run "$TMP/pyproj" --run-toolchains)
case " $(tr '\n' ' ' < "$MARKS/pip-audit" 2>/dev/null) " in
  *" -f json "*" . "*) ok "pip-audit audits a pyproject.toml target's own project directory" ;;
  *) bad "pip-audit audits a pyproject.toml target's own project directory" "-f json … ." "$(tr '\n' ' ' < "$MARKS/pip-audit" 2>/dev/null)" ;;
esac

if command -v git >/dev/null 2>&1; then
  # Three routes by which a read-only git command runs a command from the target's
  # .git/config: fsmonitor (status, ls-files), log.showSignature with gpg.program
  # (log), and a clean filter declared in .git/info/attributes (status, on a racily
  # clean file). Only the first two can be switched off from the command line.
  G="$TMP/gitexec"; mkdir -p "$G"
  ( cd "$G" && git init -q && git config user.email t@t && git config user.name t \
    && printf 'a\n' > f.txt && git add -A && git commit -qm init \
    && T=$(git rev-parse 'HEAD^{tree}') && P=$(git rev-parse HEAD) \
    && C=$(printf 'tree %s\nparent %s\nauthor t <t@t> 1700000000 +0000\ncommitter t <t@t> 1700000000 +0000\ngpgsig -----BEGIN PGP SIGNATURE-----\n \n x\n -----END PGP SIGNATURE-----\n\nsigned\n' "$T" "$P" | git hash-object -t commit -w --stdin) \
    && git update-ref "refs/heads/$(git symbolic-ref --short HEAD)" "$C" \
    && printf '#!/bin/sh\n: > "%s/gpg"\nexit 1\n' "$MARKS" > "$TMP/fakegpg" && chmod +x "$TMP/fakegpg" \
    && git config log.showSignature true && git config gpg.program "$TMP/fakegpg" \
    && git config core.fsmonitor ": > '$MARKS/fsmonitor'; false" \
    && mkdir -p .git/info && printf '*.txt filter=x\n' > .git/info/attributes \
    && git config filter.x.clean "sh -c ': > $MARKS/filter; cat'" \
    && printf 'c\n' > f.txt && git -c core.fsmonitor=false -c filter.x.clean=cat add f.txt && printf 'b\n' > f.txt ) >/dev/null 2>&1
  rm -f "$MARKS"/*
  M=$(run "$G")
  RAN=$(ls "$MARKS" | tr '\n' ' ')
  [ -z "$RAN" ] \
    && ok "default git probes run no command from the target's .git/config" \
    || bad "default git probes run no command from the target's .git/config" "no marks" "$RAN"
  case "$(status_of "$M" git-status) $(note_of "$M" git-status)" in
    "error not run"*) ok "git-status, which can run a target filter, is gated" ;;
    *) bad "git-status, which can run a target filter, is gated" "error not run…" "$(status_of "$M" git-status) $(note_of "$M" git-status)" ;;
  esac
  [ "$(status_of "$M" git-staged)" = "ok" ] && [ "$(status_of "$M" git-log)" = "ok" ] \
    && ok "filter-free git probes still report on the target" \
    || bad "filter-free git probes still report on the target" "git-staged ok, git-log ok" "git-staged=$(status_of "$M" git-staged) git-log=$(status_of "$M" git-log)"
else
  skipped "git execution tests — git not installed"
fi

echo
echo "bundle exposure"
# The default bundle held every secret-scan hit, world-readable, at a name another
# account could predict and pre-create.
TD="$TMP/tmpd"; mkdir -p "$TD"
B=$(TMPDIR="$TD" bash "$PROBE" "$TMP/sec" 2>/dev/null | tail -1)
case "$(ls -ld "$B" 2>/dev/null)" in
  drwx------*) ok "the default bundle directory is private to its owner" ;;
  *) bad "the default bundle directory is private to its owner" "drwx------" "$(ls -ld "$B" 2>&1)" ;;
esac
LEAK=$(find "$B" \( -perm -040 -o -perm -004 \) -type f -print 2>/dev/null | head -3 | tr '\n' ' ')
[ -n "$B" ] && [ -d "$B" ] && [ -z "$LEAK" ] \
  && ok "no bundle file is group- or world-readable" \
  || bad "no bundle file is group- or world-readable" "none" "${LEAK:-bundle missing: $B}"
PRE=""
i=0; while [ $i -lt 4 ]; do
  d="$TD/codebase-audit-sec-$(date -r $(( $(date +%s) + i )) +%Y%m%d-%H%M%S 2>/dev/null || date -d "@$(( $(date +%s) + i ))" +%Y%m%d-%H%M%S)"
  mkdir -p "$d"; chmod 777 "$d"; PRE="$PRE $d"; i=$((i+1))
done
B=$(TMPDIR="$TD" bash "$PROBE" "$TMP/sec" 2>/dev/null | tail -1)
ADOPTED=""; for d in $PRE; do [ -z "$(ls -A "$d")" ] || ADOPTED="$ADOPTED $d"; done
[ -n "$B" ] && [ -f "$B/manifest.tsv" ] && [ -z "$ADOPTED" ] \
  && ok "a pre-created directory at the predictable default name is not adopted" \
  || bad "a pre-created directory at the predictable default name is not adopted" "fresh bundle, pre-created dirs untouched" "bundle=$B adopted=$ADOPTED"
if [ "$(id -u)" = "0" ]; then
  mkdir -p "$TMP/notmine"; chown 65534 "$TMP/notmine"
  bash "$PROBE" "$TMP/plain" -o "$TMP/notmine" >/dev/null 2>&1; RC=$?
  [ "$RC" -eq 2 ] && [ ! -e "$TMP/notmine/manifest.tsv" ] \
    && ok "an -o directory owned by another account is refused" \
    || bad "an -o directory owned by another account is refused" "exit 2, nothing written" "exit $RC"
else
  skipped "foreign-owned -o test — needs root to chown the fixture"
fi

echo
echo "bundle placement"
# A bundle inside the target is walked by the probes while it is being written.
mkdir -p "$TMP/inside/src" "$TMP/emptytarget"; printf 'x\n' > "$TMP/inside/src/a.sh"
bash "$PROBE" "$TMP/inside" -o "$TMP/inside/bundle" >/dev/null 2>&1; RC=$?
[ "$RC" -eq 2 ] && [ ! -e "$TMP/inside/bundle" ] \
  && ok "-o inside the target is refused before anything is written" \
  || bad "-o inside the target is refused before anything is written" "exit 2, no bundle" "exit $RC, bundle $([ -e "$TMP/inside/bundle" ] && echo created || echo absent)"
bash "$PROBE" "$TMP/emptytarget" -o "$TMP/emptytarget" >/dev/null 2>&1; RC=$?
[ "$RC" -eq 2 ] && [ -z "$(ls -A "$TMP/emptytarget")" ] \
  && ok "-o naming the target itself is refused" \
  || bad "-o naming the target itself is refused" "exit 2, target untouched" "exit $RC, $(ls -A "$TMP/emptytarget" | tr '\n' ' ')"
ln -s "$TMP/inside" "$TMP/inside-link"
bash "$PROBE" "$TMP/inside" -o "$TMP/inside-link/b2" >/dev/null 2>&1; RC=$?
[ "$RC" -eq 2 ] && [ ! -e "$TMP/inside/b2" ] \
  && ok "-o reaching into the target through a symlink is refused" \
  || bad "-o reaching into the target through a symlink is refused" "exit 2, no bundle" "exit $RC"

# An exported CDPATH made `cd` print the directory, so TARGET held two lines, and
# with a same-named decoy on CDPATH it named the decoy.
mkdir -p "$TMP/cdp/real/proj" "$TMP/cdp/decoy/proj"; printf 'x\n' > "$TMP/cdp/real/proj/a.txt"
REAL=$(cd -P "$TMP/cdp/real/proj" && pwd -P)
( cd "$TMP/cdp/real" && CDPATH="$TMP/cdp/decoy" bash "$PROBE" proj -o "$TMP/b-cdpath" ) >/dev/null 2>&1
[ "$(sed -n 's/^target: *//p' "$TMP/b-cdpath/env.txt" 2>/dev/null)" = "$REAL" ] && [ "$(status_of "$TMP/b-cdpath/manifest.tsv" file-count)" = "ok" ] \
  && [ "$(cat "$TMP/b-cdpath/out/file-count.txt" 2>/dev/null)" = "1" ] \
  && ok "an exported CDPATH does not redirect or split the target" \
  || bad "an exported CDPATH does not redirect or split the target" "target: $REAL, file-count 1" "$(grep -A1 '^target' "$TMP/b-cdpath/env.txt" 2>/dev/null | tr '\n' '|') file-count=$(cat "$TMP/b-cdpath/out/file-count.txt" 2>/dev/null)"

# --- the manifest must not overclaim ----------------------------------------
echo
echo "filtered probes on an unreadable tree"
# A trailing `grep -v` filter exits 1 when nothing survives it. Under pipefail that
# 1 replaced grep -r's 2, and the row filed `empty` on a tree it could not read.
if [ "$(id -u)" != "0" ]; then
  mkdir -p "$TMP/perm3/shut" "$TMP/perm3/open"; printf '<?php echo 1;\n' > "$TMP/perm3/open/a.php"
  printf 'password = "Zq8vN3kLm2Xp9Rt4"\n' > "$TMP/perm3/shut/s.yml"
  chmod 000 "$TMP/perm3/shut"
  M=$(run "$TMP/perm3")
  chmod 755 "$TMP/perm3/shut"
  for p in secret-scan route-tables health-endpoints telemetry swallowed-exceptions; do
    [ "$(status_of "$M" $p)" = "error" ] \
      && ok "$p that could not read part of the tree and matched nothing is error" \
      || bad "$p that could not read part of the tree and matched nothing is error" error "$(status_of "$M" $p) (exit $(field "$M" $p 4))"
  done
else
  skipped "unreadable-tree filter tests — root reads everything"
fi
M=$(DOCKER_STUB_PSWARN=1 DOCKER_STUB_NONE=1 PATH="$STUB:$PATH" run "$TMP/dock" --host-containers)
case "$(status_of "$M" docker-ps) $(note_of "$M" docker-ps)" in
  "empty "*"ran clean"*) bad "an empty row with stderr does not say it ran clean" "no 'ran clean'" "$(note_of "$M" docker-ps)" ;;
  "empty "*stderr*) ok "an empty row with stderr does not say it ran clean" ;;
  *) bad "an empty row with stderr does not say it ran clean" "empty, note mentions stderr" "$(status_of "$M" docker-ps) $(note_of "$M" docker-ps)" ;;
esac

echo
echo "scanner output must be a report"
# npm exits 1 for findings and for failures that carry no "code": an unreachable
# registry and an HTTP 503 both filed ok in v1.3.0. Only a report counts.
NSTUB="$TMP/npmbin"; mkdir -p "$NSTUB"
cat > "$NSTUB/npm" <<'STUBEOF'
#!/bin/sh
[ "$1" = audit ] || { echo '{}'; exit 0; }
case "${NPM_STUB:-}" in
  refused) printf '{\n  "message": "request to http://127.0.0.1:9/-/npm/v1/security/advisories/bulk failed, reason: connect ECONNREFUSED 127.0.0.1:9",\n  "error": {\n    "summary": "",\n    "detail": ""\n  }\n}\n'; exit 1 ;;
  503) printf '{\n  "message": "503 Service Unavailable - POST http://127.0.0.1:18765/-/npm/v1/security/advisories/bulk",\n  "error": {\n    "summary": "",\n    "detail": ""\n  }\n}\n'; exit 1 ;;
  vulns) printf '{\n  "auditReportVersion": 2,\n  "vulnerabilities": {\n    "lodash": {"severity": "high"}\n  },\n  "metadata": {}\n}\n'; exit 1 ;;
esac
STUBEOF
cat > "$NSTUB/pip-audit" <<'STUBEOF'
#!/bin/sh
case "${PIP_STUB:-}" in
  fail) echo "ERROR:pip_audit._cli:Invalid requirement: 'django=2.2.0'" >&2; exit 1 ;;
  vulns) echo '{"dependencies": [{"name": "django", "version": "2.2.0", "vulns": [{"id": "PYSEC-2019-13"}]}], "fixes": []}'; exit 1 ;;
esac
STUBEOF
chmod +x "$NSTUB/npm" "$NSTUB/pip-audit"
mkdir -p "$TMP/npmt" "$TMP/pipt"; printf '{"name":"x"}\n' > "$TMP/npmt/package.json"; printf 'django==2.2.0\n' > "$TMP/pipt/requirements.txt"
for mode in refused 503; do
  M=$(NPM_STUB=$mode PATH="$NSTUB:$PATH" run "$TMP/npmt" --run-toolchains)
  [ "$(status_of "$M" npm-audit)" = "error" ] \
    && ok "npm audit that could not reach its registry ($mode) is error" \
    || bad "npm audit that could not reach its registry ($mode) is error" error "$(status_of "$M" npm-audit)"
done
case "$(note_of "$M" npm-audit)" in
  *"503 Service Unavailable"*) ok "the error note quotes the tool's own message" ;;
  *) bad "the error note quotes the tool's own message" "…503 Service Unavailable…" "$(note_of "$M" npm-audit)" ;;
esac
M=$(NPM_STUB=vulns PATH="$NSTUB:$PATH" run "$TMP/npmt" --run-toolchains)
[ "$(status_of "$M" npm-audit)" = "ok" ] \
  && ok "npm audit exiting 1 with a vulnerability report is ok" \
  || bad "npm audit exiting 1 with a vulnerability report is ok" ok "$(status_of "$M" npm-audit): $(note_of "$M" npm-audit)"
M=$(PIP_STUB=fail PATH="$NSTUB:$PATH" run "$TMP/pipt" --run-toolchains)
[ "$(status_of "$M" pip-audit)" = "error" ] \
  && ok "pip-audit that printed no report is error, not empty" \
  || bad "pip-audit that printed no report is error, not empty" error "$(status_of "$M" pip-audit)"
M=$(PIP_STUB=vulns PATH="$NSTUB:$PATH" run "$TMP/pipt" --run-toolchains)
[ "$(status_of "$M" pip-audit)" = "ok" ] \
  && ok "pip-audit exiting 1 with a JSON report is ok" \
  || bad "pip-audit exiting 1 with a JSON report is ok" ok "$(status_of "$M" pip-audit): $(note_of "$M" pip-audit)"

echo
echo "host container failures"
# `docker exec … >/dev/null 2>&1` read a refused exec as "client not installed".
M=$(DOCKER_STUB_EXECFAIL=1 PATH="$STUB:$PATH" run "$TMP/dock" --host-containers)
[ "$(status_of "$M" db-clients)" != "empty" ] && [ "$(status_of "$M" db-clients)" != "ok" ] && [ "$(field "$M" db-clients 7)" = "yes" ] \
  && ok "a refused docker exec is not read as no client installed" \
  || bad "a refused docker exec is not read as no client installed" "error, stderr yes" "$(status_of "$M" db-clients), stderr=$(field "$M" db-clients 7)"
M=$(DOCKER_STUB_PSFAIL=1 PATH="$STUB:$PATH" run "$TMP/dock" --host-containers)
[ "$(status_of "$M" db-clients)" = "error" ] \
  && ok "db-clients with the daemon unreachable is error" \
  || bad "db-clients with the daemon unreachable is error" error "$(status_of "$M" db-clients)"
M=$(PATH="$STUB:$PATH" run "$TMP/dock" --host-containers)
[ "$(cat "$(dirname "$M")/out/db-clients.txt" 2>/dev/null)" = "c1: mariadb" ] \
  && ok "db-clients names the container and the client it found" \
  || bad "db-clients names the container and the client it found" "c1: mariadb" "$(tr '\n' '|' < "$(dirname "$M")/out/db-clients.txt" 2>/dev/null)"

echo
echo "timeout values"
M=$(run "$TMP/plain" --timeout 00)
grep -q '^timeout: *none — disabled' "$(dirname "$M")/env.txt" \
  && ok "--timeout 00 is recorded as disabled" \
  || bad "--timeout 00 is recorded as disabled" "none — disabled" "$(grep '^timeout' "$(dirname "$M")/env.txt")"
bash "$PROBE" "$TMP/plain" --timeout 99999999999999999999 -o "$TMP/b-bigt" >/dev/null 2>&1; RC=$?
[ "$RC" -eq 2 ] && [ ! -e "$TMP/b-bigt" ] \
  && ok "an out-of-range --timeout is rejected" \
  || bad "an out-of-range --timeout is rejected" "exit 2" "exit $RC"

echo
echo "secret-scan shapes"
# v1.3.0's pattern was case-sensitive, its placeholder filter read the path and
# every PHP $variable, and grep skipped build/, dist/ and .venv/.
L='Zq8vN3kLm2Xp9Rt4Wc7Y'
mkdir -p "$TMP/envkeys"
printf 'DB_PASSWORD=%s\nSTRIPE_SECRET_KEY=sk_live_%s\nAWS_SECRET_ACCESS_KEY=%s\nOPENAI_API_KEY="sk-proj-%s"\n' $L $L $L $L > "$TMP/envkeys/.env"
printf 'services:\n  db:\n    environment:\n      MYSQL_ROOT_PASSWORD: %s\n      - MYSQL_PASSWORD=%s\n' $L $L > "$TMP/envkeys/docker-compose.yml"
printf 'Password = "%s"\n' $L > "$TMP/envkeys/settings.py"
mkdir -p "$TMP/shapes"
printf '<?php\n$password = "%s";\ndefine('"'"'DB_PASSWORD'"'"', '"'"'%s'"'"');\n$c = ['"'"'secret'"'"' => '"'"'%s'"'"'];\n$dsn = "mysql://root:%s@db:3306/app";\n' $L $L $L $L > "$TMP/shapes/config.php"
printf '{\n  "password": "%s"\n}\n' $L > "$TMP/shapes/app.json"
printf 'export API_TOKEN=%s\n' $L > "$TMP/shapes/deploy.sh"
printf 'const apiKey = "%s";\n' $L > "$TMP/shapes/client.ts"
mkdir -p "$TMP/secpaths/examples/app" "$TMP/secpaths/deploy/build" "$TMP/secpaths/config/dist" "$TMP/secpaths/src" "$TMP/secpaths/functions"
for f in examples/app/prod.yml deploy/build/.env config/dist/settings.yml src/sample_loader.py functions/handler.js plain.yml; do
  printf 'password = "%s"\n' $L > "$TMP/secpaths/$f"
done
# …and the same literal inside third-party trees, which are not the target's code.
mkdir -p "$TMP/secpaths/node_modules/pkg" "$TMP/secpaths/vendor/lib"
printf 'password = "%s"\n' $L > "$TMP/secpaths/node_modules/pkg/c.yml"; printf 'password = "%s"\n' $L > "$TMP/secpaths/vendor/lib/c.yml"
# …and in minified bundles, source maps and lockfiles, which match anything.
printf 'var password="%s";\n' $L > "$TMP/secpaths/app.min.js"; printf '{"token": "%s"}\n' $L > "$TMP/secpaths/package-lock.json"
# The shortest literal reported is 6 characters.
printf 'password: abc12\npassword: abc123\n' > "$TMP/secpaths/short.yml"
for t in envkeys:7 shapes:7 secpaths:6; do
  d=${t%%:*}; n=${t##*:}
  M=$(run "$TMP/$d"); F="$(dirname "$M")/out/secret-scan.txt"
  N=$(grep -c "$L" "$F" 2>/dev/null); N=${N:-0}
  [ "$N" = "$n" ] \
    && ok "secret-scan finds all $n credentials in the $d fixture" \
    || bad "secret-scan finds all $n credentials in the $d fixture" "$n" "$N found: $(cut -d: -f1,2 "$F" 2>/dev/null | tr '\n' ' ')"
done
# A key assigned a function call is not a literal. Dropping it must not drop a
# literal that merely shares a line with a call.
mkdir -p "$TMP/calls"
printf 'const passwordField = document.getElementById("pw");\nconst tokenExpiry = Date.now();\n' > "$TMP/calls/form.js"
printf 'db = connect(password="%s")\n' $L > "$TMP/calls/db.py"
M=$(run "$TMP/secpaths"); F="$(dirname "$M")/out/secret-scan.txt"
[ "$(grep -c 'short.yml' "$F")" = "1" ] && grep -q 'short.yml:2:' "$F" \
  && ok "a 6-character literal is reported and a 5-character one is not" \
  || bad "a 6-character literal is reported and a 5-character one is not" "short.yml:2 only" "$(grep short.yml "$F" | cut -d: -f1,2 | tr '\n' ' ')"
M=$(run "$TMP/calls"); F="$(dirname "$M")/out/secret-scan.txt"
[ "$(cut -d: -f1 "$F" 2>/dev/null | tr '\n' ' ')" = "./db.py " ] \
  && ok "a key assigned a function call is not reported; a literal beside a call is" \
  || bad "a key assigned a function call is not reported; a literal beside a call is" "./db.py only" "$(cut -d: -f1,2 "$F" 2>/dev/null | tr '\n' ' ')"
# Lines from a real repository that the widened pattern first reported: plural
# keys and comma-separated lists are code, not credentials.
mkdir -p "$TMP/noise"
printf 'span_tokens = fields["span_total_tokens"]\nkeys = ("input_tokens", "output_tokens",\n' > "$TMP/noise/ledger.py"
printf 'logs (tokens, first-token latency, model) into SQLite\nreturns token, expires_at, and scope\n' > "$TMP/noise/README.md"
printf 'const secretKey = "%s";\n' $L > "$TMP/noise/keys.ts"
M=$(run "$TMP/noise"); F="$(dirname "$M")/out/secret-scan.txt"
[ "$(cut -d: -f1 "$F" 2>/dev/null | tr '\n' ' ')" = "./keys.ts " ] \
  && ok "plural keys and comma lists are not reported; secretKey is" \
  || bad "plural keys and comma lists are not reported; secretKey is" "./keys.ts only" "$(cut -d: -f1,2 "$F" 2>/dev/null | tr '\n' ' ')"
M=$(run "$TMP/plain")
case "$(note_of "$M" secret-scan)" in
  *"no assigned literal"*) bad "an empty secret-scan does not claim no literal exists" "no such claim" "$(note_of "$M" secret-scan)" ;;
  *) ok "an empty secret-scan does not claim no literal exists" ;;
esac

echo
echo "generated and vendored trees"
mkdir -p "$TMP/skipdirs/src"; printf 'x = 1\n' > "$TMP/skipdirs/src/app.py"
for d in .venv/lib venv/lib target/debug dist build coverage bower_components/x __pycache__ third_party/x vendor/lib node_modules/p; do
  mkdir -p "$TMP/skipdirs/$d"; printf '%01000d\n' 0 > "$TMP/skipdirs/$d/big.bin"
done
M=$(run "$TMP/skipdirs"); OUT="$(dirname "$M")/out"
[ "$(cat "$OUT/file-count.txt")" = "1" ] && [ "$(wc -l < "$OUT/largest-files.txt" | tr -d ' ')" = "1" ] && ! grep -q bin "$OUT/lang-census.txt" \
  && ok "find probes skip the same generated trees the grep probes skip" \
  || bad "find probes skip the same generated trees the grep probes skip" "file-count 1, one largest file, no .bin" "file-count $(cat "$OUT/file-count.txt"), largest $(head -1 "$OUT/largest-files.txt"), census $(tr '\n' ' ' < "$OUT/lang-census.txt")"

echo
echo "build definitions"
mkdir -p "$TMP/builds/a" "$TMP/builds/b" "$TMP/builds/c"
printf 'FROM node:latest\nRUN echo ok\n' > "$TMP/builds/a/Dockerfile"
printf 'FROM alpine:3.19\nADD http://example.invalid/y /y\n' > "$TMP/builds/b/Containerfile"
printf 'FROM alpine:3.19\nRUN wget -qO- https://example.invalid/i | sh\n' > "$TMP/builds/b/app.Dockerfile"
printf 'from python AS base\nRUN echo ok\n' > "$TMP/builds/c/Dockerfile.dev"
M=$(run "$TMP/builds"); OUT="$(dirname "$M")/out"
[ "$(wc -l < "$OUT/dockerfiles.txt" | tr -d ' ')" = "4" ] \
  && ok "Containerfile and *.Dockerfile are found as build definitions" \
  || bad "Containerfile and *.Dockerfile are found as build definitions" 4 "$(tr '\n' ' ' < "$OUT/dockerfiles.txt")"
[ "$(wc -l < "$OUT/dockerfile-fetches.txt" | tr -d ' ')" = "4" ] \
  && ok "dockerfile-fetches finds :latest, an untagged FROM, ADD http:// and wget" \
  || bad "dockerfile-fetches finds :latest, an untagged FROM, ADD http:// and wget" 4 "$(cut -d: -f1,2 "$OUT/dockerfile-fetches.txt" | tr '\n' ' ')"

echo
echo "every probe reports on a target that has what it looks for"
# One fixture holding something for every probe. A probe whose command is replaced
# with `true` must turn one of these rows red.
SF="$TMP/surface"; mkdir -p "$SF/.github/workflows" "$SF/tests"
printf '{}\n' > "$SF/composer.json"; printf '{"name":"s"}\n' > "$SF/package.json"
printf 'services:\n  web:\n    ports:\n      - "8080:80"\n' > "$SF/docker-compose.yml"
printf 'FROM node:latest\n' > "$SF/Dockerfile"; : > "$SF/.env.example"; : > "$SF/.editorconfig"; : > "$SF/LICENSE"
printf 'on: push\n' > "$SF/.github/workflows/ci.yml"; printf '<?php echo 1;\n' > "$SF/tests/a_test.php"
printf '![ci](https://github.com/x/y/actions/workflows/ci.yml/badge.svg)\n' > "$SF/README.md"
printf '<?php\n// GET /patients\n$r = "GET /api/patients";\n' > "$SF/routes.php"
printf '<?php // /healthz\n' > "$SF/health.php"; printf '<?php use Monolog\\Logger;\n' > "$SF/log.php"
printf 'exporter: opentelemetry\n' > "$SF/otel.yml"; printf '<?php\ntry { f(); } catch (Exception $e) {\n}\n' > "$SF/err.php"
printf 'api_key: 9f8a7b6c5d4e3f21\n' > "$SF/config.yml"; printf 'if then\n' > "$SF/bad.sh"
printf '[submodule "x"]\n\tpath = x\n\turl = https://example.invalid/x.git\n' > "$SF/.gitmodules"
if command -v git >/dev/null 2>&1; then
  ( cd "$SF" && git init -q && git config user.email t@t && git config user.name t \
    && git remote add origin https://example.invalid/s.git && git add -A && git commit -qm init && git tag v1 \
    && printf 'x\n' >> otel.yml && git add otel.yml && : > untracked.txt ) >/dev/null 2>&1
fi
M=$(PATH="$CSTUB:$STUB:$PATH" run "$SF" --host-containers)
PROBES="dockerfiles dockerfile-fetches compose-files docker-ps db-clients secret-scan env-files published-ports route-tables route-verbs lint-config lang-census php-syntax shell-lint test-inventory test-file-count ci-config ci-badges health-endpoints log-surface telemetry swallowed-exceptions repo-size largest-files file-count license-files composer-manifest npm-manifest"
command -v git >/dev/null 2>&1 && PROBES="$PROBES git-remotes git-log git-commit-count git-authors git-staged git-untracked git-tracked git-tags git-submodules git-churn"
for p in $PROBES; do
  [ "$(status_of "$M" $p)" = "ok" ] \
    && ok "$p reports what the fixture holds" \
    || bad "$p reports what the fixture holds" ok "$(status_of "$M" $p): $(note_of "$M" $p)"
done

# Scanners signal findings with their exit. Each of these exits the way the real
# tool does when it finds something, with a report.
FSTUB="$TMP/findingsbin"; mkdir -p "$FSTUB"
printf '#!/bin/sh\necho "Found 1 security vulnerability advisory affecting 1 package"\nexit 1\n' > "$FSTUB/composer"
printf '#!/bin/sh\necho "Vulnerability #1: GO-2024-0001"\nexit 3\n' > "$FSTUB/govulncheck"
printf '#!/bin/sh\necho "Crate: x  ID: RUSTSEC-2024-0001"\nexit 1\n' > "$FSTUB/cargo-audit"
printf '#!/bin/sh\necho "Name: rack"\necho "Vulnerable"\nexit 1\n' > "$FSTUB/bundler-audit"
chmod +x "$FSTUB"/*
FX="$TMP/findings"; mkdir -p "$FX"
printf '{}\n' > "$FX/composer.json"; printf '{"name":"f"}\n' > "$FX/package.json"; printf 'django==2.2.0\n' > "$FX/requirements.txt"
printf 'module f\n' > "$FX/go.mod"; printf '[package]\nname = "f"\n' > "$FX/Cargo.toml"; printf 'source "https://rubygems.org"\n' > "$FX/Gemfile"
PROBES="composer-audit npm-audit pip-audit go-vulncheck cargo-audit bundler-audit dep-licenses"
if command -v git >/dev/null 2>&1; then
  ( cd "$FX" && git init -q && git config user.email t@t && git config user.name t && git add -A && git commit -qm i && : > new.txt ) >/dev/null 2>&1
  PROBES="$PROBES git-status"
fi
M=$(NPM_STUB=vulns PIP_STUB=vulns PATH="$FSTUB:$NSTUB:$PATH" run "$FX" --run-toolchains)
for p in $PROBES; do
  [ "$(status_of "$M" $p)" = "ok" ] \
    && ok "$p with findings is ok" \
    || bad "$p with findings is ok" ok "$(status_of "$M" $p): $(note_of "$M" $p)"
done

echo
echo "lint directives"
# ShellCheck reads any comment starting `# shellcheck ` as a directive. probe.sh
# had one that was prose, and shellcheck stopped analysing the file there.
SD="$(dirname "$PROBE")"
BADDIR=$(grep -nE '^[[:space:]]*#[[:space:]]*shellcheck[[:space:]]' "$SD/probe.sh" "$SD/test_probe.sh" | grep -vE 'shellcheck[[:space:]]+(disable|enable|source|shell|external-sources)=' | cut -d: -f1,2 | tr '\n' ' ')
[ -z "$BADDIR" ] \
  && ok "no prose comment is parsed by shellcheck as a directive" \
  || bad "no prose comment is parsed by shellcheck as a directive" "none" "$BADDIR"

echo
echo "-----------------------------------------"
printf '%d passed, %d failed, %d skipped\n' "$PASS" "$FAIL" "$SKIP"
[ "$FAIL" -eq 0 ] || exit 1
