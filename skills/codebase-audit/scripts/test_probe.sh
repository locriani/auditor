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
PASS=0; FAIL=0

ok()   { PASS=$((PASS+1)); printf '  ok    %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  FAIL  %s\n       expected: %s\n       actual:   %s\n' "$1" "$2" "$3"; }
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
cat > "$STUB/cargo" <<'STUBEOF'
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
chmod +x "$STUB/cargo" "$STUB/npm"
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
  ps) echo c1 ;;
  exec) case "$*" in *"command -v mariadb"*) exit 0 ;; *) exit 1 ;; esac ;;
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

# Placeholders must not be reported as secrets, or every result is noise.
mkdir -p "$TMP/ph"; printf 'password: changeme\napi_key: your_key_here\ntoken: ${FROM_ENV}\n' > "$TMP/ph/conf.yml"
M=$(run "$TMP/ph")
[ "$(status_of "$M" secret-scan)" = "empty" ] \
  && ok "placeholder values are filtered out" \
  || bad "placeholder values are filtered out" empty "$(status_of "$M" secret-scan)"

# --- unreadable input must never read as clean ------------------------------
echo
echo "unreadable input"
mkdir -p "$TMP/perm/open" "$TMP/perm/shut"
printf 'token: aaaaaaaaaaaa\n' > "$TMP/perm/shut/x.yml"
chmod 000 "$TMP/perm/shut"
M=$(run "$TMP/perm")
[ "$(field "$M" secret-scan 7)" = "yes" ] \
  && ok "unreadable subtree is flagged via stderr column" \
  || bad "unreadable subtree is flagged via stderr column" yes "$(field "$M" secret-scan 7)"
case "$(note_of "$M" secret-scan)" in
  *"stderr present"*) ok "note names the stderr file" ;;
  *) bad "note names the stderr file" "mentions stderr" "$(note_of "$M" secret-scan)" ;;
esac
chmod 755 "$TMP/perm/shut"

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

# -o must never clear a directory probe.sh did not create. v1.2.0 ran rm -rf on
# any out/ it found.
mkdir -p "$TMP/victim/out"; printf 'keep me\n' > "$TMP/victim/out/user-data.txt"
bash "$PROBE" "$TMP/plain" -o "$TMP/victim" >/dev/null 2>&1; RC=$?
[ "$RC" -eq 2 ] && [ -f "$TMP/victim/out/user-data.txt" ] \
  && ok "an unmarked non-empty -o directory is refused and left intact" \
  || bad "an unmarked non-empty -o directory is refused and left intact" "exit 2, file kept" "exit $RC, file $([ -f "$TMP/victim/out/user-data.txt" ] && echo kept || echo GONE)"

# --timeout is interpolated into eval; anything but digits must be rejected
# before a single probe runs.
PWN="$TMP/pwned"
bash "$PROBE" "$TMP/plain" -o "$TMP/b-inj" --timeout "1; touch $PWN" >/dev/null 2>&1; RC=$?
[ "$RC" -eq 2 ] && [ ! -e "$PWN" ] && [ ! -e "$TMP/b-inj" ] \
  && ok "a non-numeric --timeout is rejected before anything runs" \
  || bad "a non-numeric --timeout is rejected before anything runs" "exit 2, nothing created" "exit $RC, pwned=$([ -e "$PWN" ] && echo yes || echo no), bundle=$([ -e "$TMP/b-inj" ] && echo yes || echo no)"

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
M=$(PATH="$STUB:$PATH" run "$TMP/crate")
[ "$(status_of "$M" cargo-audit)" = "output" ] \
  && ok "nonzero exit outside ok_exits WITH stdout classifies as output" \
  || bad "nonzero exit outside ok_exits WITH stdout classifies as output" output "$(status_of "$M" cargo-audit)"

# npm audit exits 1 both when it finds vulnerabilities and when it cannot audit.
mkdir -p "$TMP/nolock"; printf '{"name":"x","version":"1.0.0"}\n' > "$TMP/nolock/package.json"
M=$(PATH="$STUB:$PATH" run "$TMP/nolock")
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
else
  echo "  skip  error-status test — git not installed"
fi

# --- testing axis -----------------------------------------------------------
echo
echo "test discovery"
mkdir -p "$TMP/shtests"; : > "$TMP/shtests/test_one.sh"; : > "$TMP/shtests/two_test.sh"
M=$(run "$TMP/shtests")
[ "$(cat "$(dirname "$M")/out/test-file-count.txt")" = "2" ] \
  && ok "shell test files are counted" \
  || bad "shell test files are counted" 2 "$(cat "$(dirname "$M")/out/test-file-count.txt")"

# --- exit status carries the producer's failure ----------------------------
# v1.2.x ended most commands in `| head`, so the exit column was head's and a
# find that could not read the tree reported 0 and `empty`.
echo
echo "exit status and unreadable targets"
mkdir -p "$TMP/perm2/shut"; : > "$TMP/perm2/shut/Dockerfile"; : > "$TMP/perm2/shut/a.js"
chmod 000 "$TMP/perm2/shut"
M=$(run "$TMP/perm2")
for p in dockerfiles lang-census; do
  [ "$(status_of "$M" $p)" != "empty" ] \
    && ok "$p on an unreadable subtree is not empty" \
    || bad "$p on an unreadable subtree is not empty" "error or output" "empty (exit $(field "$M" $p 4))"
done
chmod 755 "$TMP/perm2/shut"
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

# Checkers run through xargs report findings as a nonzero exit, and BSD xargs
# passes that on as 1 where GNU uses 123. Both must read as results.
mkdir -p "$TMP/checkers"; printf 'FROM alpine\n' > "$TMP/checkers/Dockerfile"; printf 'if then\n' > "$TMP/checkers/bad.sh"
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
[ "$(status_of "$M" shell-lint)" != "ok" ] && [ "$(status_of "$M" shell-lint)" != "empty" ] \
  && ok "shellcheck unable to check a file is not ok" \
  || bad "shellcheck unable to check a file is not ok" "output or error" "$(status_of "$M" shell-lint)"

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
grep -q '\./sp ace/big file\.txt$' "$OUT/largest-files.txt" \
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
else
  echo "  skip  no-binary env.txt test — this host has a timeout binary"
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
  # A subdirectory of a work tree IS version controlled. v1.0.0 said otherwise.
  M=$(run "$TMP/repo/nested")
  [ "$(status_of "$M" git-commit-count)" != "n/a" ] \
    && ok "a subdirectory of a work tree is not reported as unversioned" \
    || bad "a subdirectory of a work tree is not reported as unversioned" "not n/a" "n/a"
else
  echo "  skip  git tests — git not installed"
fi

echo
echo "-----------------------------------------"
printf '%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
