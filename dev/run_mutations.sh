#!/usr/bin/env bash
#
# run_mutations.sh — run test_probe.sh against every mutant in dev/mutations.py.
#
#   bash dev/run_mutations.sh [-j JOBS] [-k] [ID ...]
#
# -j  parallel suites (default 6)     -k  keep the work directory
# IDs restrict the run to those mutants.
#
# Prints one row per mutant — killed, SURVIVED, equivalent, or n/a on this host —
# and exits 1 if any applicable, non-equivalent mutant survived, or if the
# unmutated suite fails under the same conditions.
#
# Every suite runs with a guard directory first on PATH holding a stand-in for each
# scanner and docker that exits 99. A mutant that removes a gate would otherwise
# run real toolchains, or enumerate this machine's containers.

set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
JOBS=6; KEEP=0
while getopts j:k o; do case $o in j) JOBS=$OPTARG ;; k) KEEP=1 ;; *) exit 2 ;; esac; done
shift $((OPTIND-1))
command -v python3 >/dev/null 2>&1 || { echo "python3 is required to build mutants" >&2; exit 2; }

WORK=$(mktemp -d)
[ "$KEEP" -eq 1 ] || trap 'chmod -R u+rwX "$WORK" 2>/dev/null; rm -rf "$WORK"' EXIT
GUARD="$WORK/guard"; mkdir -p "$GUARD"
for t in docker npm composer pip-audit govulncheck cargo cargo-audit bundle bundler-audit; do
  printf '#!/bin/sh\necho "guard: %s is not run under mutation testing" >&2\nexit 99\n' "$t" > "$GUARD/$t"
done
chmod +x "$GUARD"/*
export PATH="$GUARD:$PATH"

python3 "$HERE/mutations.py" build "$WORK/m" >/dev/null || exit 2

# Host conditions a mutant may require.
HAVE=""
command -v timeout >/dev/null 2>&1 || command -v gtimeout >/dev/null 2>&1 || HAVE="$HAVE no-timeout"
command -v shellcheck >/dev/null 2>&1 || HAVE="$HAVE no-shellcheck"
if [ "$(id -u)" = "0" ]; then HAVE="$HAVE root"; else HAVE="$HAVE non-root"; fi

echo "control: unmutated suite"
bash "$HERE/../skills/codebase-audit/scripts/test_probe.sh" > "$WORK/control.txt" 2>&1 \
  || { echo "  the unmutated suite fails under the guard — fix that first"; tail -5 "$WORK/control.txt"; exit 1; }
echo "  $(tail -1 "$WORK/control.txt")"

one() { # one <id>
  bash "$WORK/m/$1/test_probe.sh" > "$WORK/m/$1/result.txt" 2>&1
  echo $? > "$WORK/m/$1/rc"
}
export -f one; export WORK

IDS="$*"
[ -n "$IDS" ] || IDS=$(cut -f1 "$WORK/m/index.tsv" | tr '\n' ' ')
RUN=""
for id in $IDS; do
  req=$(awk -F'\t' -v i="$id" '$1==i {print $2}' "$WORK/m/index.tsv")
  [ -n "$req" ] || { echo "unknown mutant: $id" >&2; exit 2; }
  ok=1; for r in $req; do [ "$r" = "-" ] && continue; case " $HAVE " in *" $r "*) ;; *) ok=0 ;; esac; done
  [ "$ok" -eq 1 ] && RUN="$RUN $id"
done
echo "running $(echo $RUN | wc -w | tr -d ' ') mutants, $JOBS at a time"
printf '%s\n' $RUN | xargs -n1 -P "$JOBS" bash -c 'one "$1"' _

KILLED=0; SURVIVED=0; EQUIV=0; NA=0; SURV=""
printf '\n%-24s %-11s %s\n' mutant result description
while IFS="$(printf '\t')" read -r id req equiv desc; do
  case " $IDS " in *" $id "*) ;; *) continue ;; esac
  case " $RUN " in
    *" $id "*)
      if [ "$(cat "$WORK/m/$id/rc")" != "0" ]; then res=killed; KILLED=$((KILLED+1))
      elif [ "$equiv" != "-" ]; then res=equivalent; EQUIV=$((EQUIV+1)); desc="$desc — $equiv"
      else res=SURVIVED; SURVIVED=$((SURVIVED+1)); SURV="$SURV $id"; fi ;;
    *) res="n/a here"; NA=$((NA+1)); desc="$desc (needs: $req)" ;;
  esac
  printf '%-24s %-11s %s\n' "$id" "$res" "$desc"
done < "$WORK/m/index.tsv"
printf '\nkilled %d · survived %d · equivalent %d · not applicable on this host %d\n' "$KILLED" "$SURVIVED" "$EQUIV" "$NA"
[ "$KEEP" -eq 0 ] || echo "work directory kept: $WORK"
[ "$SURVIVED" -eq 0 ] || { echo "survivors:$SURV"; exit 1; }
