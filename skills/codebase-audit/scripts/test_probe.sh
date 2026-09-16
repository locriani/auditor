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
mkdir -p "$TMP/many"
i=0; while [ $i -lt 40 ]; do printf 'x\n' > "$TMP/many/f$i.aaa"; i=$((i+1)); done
M=$(run "$TMP/many")
[ -n "$(awk -F'\t' 'NR>1 && $9 ~ /^TRUNCATED/' "$M")" ] || \
  [ "$(field "$M" lang-census 6)" -lt 20 ] \
  && ok "output at the line cap is flagged TRUNCATED" \
  || bad "output at the line cap is flagged TRUNCATED" "TRUNCATED note" "none"

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
mkdir -p "$TMP/r1" "$TMP/r2"; printf 'password: zzzzzzzzzzzz\n' > "$TMP/r1/c.yml"
bash "$PROBE" "$TMP/r1" -o "$TMP/b-reuse" >/dev/null 2>&1
bash "$PROBE" "$TMP/r2" -o "$TMP/b-reuse" >/dev/null 2>&1
[ ! -s "$TMP/b-reuse/out/secret-scan.txt" ] \
  && ok "a reused bundle does not retain the previous target's evidence" \
  || bad "a reused bundle does not retain the previous target's evidence" "empty" "stale content"

M="$TMP/b-reuse/manifest.tsv"
[ "$(head -1 "$M" | awk -F'\t' '{print NF}')" -eq 9 ] \
  && ok "manifest header has all 9 columns" \
  || bad "manifest header has all 9 columns" 9 "$(head -1 "$M" | awk -F'\t' '{print NF}')"

BAD=$(awk -F'\t' 'NR>1 && NF!=9 {print $1}' "$M" | tr '\n' ' ')
[ -z "$BAD" ] && ok "every manifest row has 9 columns" || bad "every manifest row has 9 columns" "all 9" "$BAD"

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
