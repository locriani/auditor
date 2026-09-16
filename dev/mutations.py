#!/usr/bin/env python3
"""mutations.py — the mutation list behind test_probe.sh's coverage claim.

Each mutation is a literal, count-checked substitution in probe.sh that breaks one
behaviour. A mutant the suite still passes is a behaviour no test pins.

    python3 dev/mutations.py build <dir>   write <dir>/<id>/{probe.sh,test_probe.sh}
                                           and <dir>/index.tsv
    python3 dev/mutations.py list          print id, requires, equivalent, description

run_mutations.sh drives both. Numbering: m01–m58 are the v1.3.0 self-audit's
mutations, re-based onto the current text (m44 became the s-* series); n* are
mutations of the fixes made after that audit; s-<probe> replaces one probe's
command with `true`, asking whether any test notices that probe measuring nothing.

requires   host conditions under which the mutant CAN be killed. On other hosts the
           branch it mutates never runs, and the runner reports "not applicable".
             no-timeout   neither timeout nor gtimeout on PATH
             no-shellcheck shellcheck not on PATH
             root / non-root
equivalent a reason the mutant cannot change observable behaviour. Reported, never
           counted as a survivor.
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, '..', 'skills', 'codebase-audit', 'scripts')

# (id, description, [(old, new, count)], requires, equivalent)
M = [
    ('m01', 'TRUNCATED at exactly the cap', [(r'[ "$_total" -gt "$_cap" ]', r'[ "$_total" -ge "$_cap" ]', 1)], '', ''),
    ('m02', 'capped file keeps cap-1 lines', [(r'head -n "$_cap" "$_full"', r'head -n "$((_cap-1))" "$_full"', 1)], '', ''),
    ('m03', 'untruncated output leaves a stray .full.txt', [(r'mv -f "$_full" "$_out"', r'cp -f "$_full" "$_out"', 1)], '', ''),
    ('m04', 'TRUNCATED note misreports the population', [(r'$_cap of $_total lines', r'$_cap of $_cap lines', 1)], '', ''),
    ('m05', 'bytes and lines columns swapped', [(r'"$_rc" "$_bytes" "$_lines"', r'"$_rc" "$_lines" "$_bytes"', 1)], '', ''),
    ('m06', 'exit column always 0', [(r'"$_name" "$_axis" "$_status" "$_rc"', r'"$_name" "$_axis" "$_status" "0"', 1)], '', ''),
    ('m07', 'valid_if check disabled', [(r'elif [ -n "$_validpat" ] && ! grep -qE', r'elif false && ! grep -qE', 1)], '', ''),
    ('m08', 'npm report pattern accepts an error object', [(r'"(auditReportVersion|vulnerabilities)"', r'"(auditReportVersion|vulnerabilities|error)"', 1)], '', ''),
    ('m09', 'TIMED OUT no longer requires a timeout binary', [(r'if [ -n "$TIMEOUT_BIN" ] && [ "$_rc" = "124" ]', r'if [ "$_rc" = "124" ]', 1)], '',
     'differs only when a probe itself exits 124 with no timeout binary; no probe command does'),
    ('m10', 'TIMED OUT branch unreachable', [(r'[ "$_rc" = "124" ]; then', r'[ "$_rc" = "99999" ]; then', 1)], '', ''),
    ('m11', 'error note no longer quotes stderr', [(r'_note=$(head -c 160 "$_err"', r'_note=$(head -c 0 "$_err"', 1)], '', ''),
    ('m12', 'stderr column always no', [(r'if [ -s "$_err" ]; then _haserr="yes"', r'if false; then _haserr="yes"', 1)], '', ''),
    ('m13', 'non-empty .err deleted', [(r'else _haserr="no"; rm -f "$_err"; fi', r'else _haserr="no"; fi; rm -f "$_err"', 1)], '', ''),
    ('m14', 'output status collapsed into error', [(r'_status="output"', r'_status="error"', 1)], '', ''),
    ('m15', 'empty status collapsed into ok', [(r'_status="empty"; _note=', r'_status="ok"; _note=', 2)], '', ''),
    ('m16', 'default ok_exits widened to 0 1', [(r'_ok="${4:-0}"', r'_ok="${4:-0 1}"', 1)], '', ''),
    ('m17', 'pipefail removed from the probe bash', [(r'"$BASH" -o pipefail -c', r'"$BASH" -c', 1)], '', ''),
    ('m18', 'probe runs even if cd into the target fails', [(r'( cd "$TARGET" && exec', r'( cd "$TARGET" ; exec', 1)], '',
     'TARGET is resolved with cd -P before any probe; a target that cannot be entered exits the script there'),
    ('m19', 'timeout never wraps probes', [(r'TIMEOUT_PREFIX="$TIMEOUT_BIN $PTIMEOUT"', r'TIMEOUT_PREFIX=""', 1)], '', ''),
    ('m20', '--timeout 0 still applies a binary', [(r'if [ "$PTIMEOUT" != "0" ]; then', r'if true; then', 1)], '', ''),
    ('m21', 'empty --timeout accepted', [(r"''|*[!0-9]*)", r"*[!0-9]*)", 1)], '', ''),
    ('m22', 'gtimeout never detected', [(r'elif command -v gtimeout ', r'elif command -v gtimeout-nope ', 1)], 'no-timeout', ''),
    ('m23', 'reuse clears only out/*.txt', [('  rm -rf "$BUNDLE/out"\n', '  rm -f "$BUNDLE"/out/*.txt\n', 1)], '', ''),
    ('m24', 'refusal exits 0', [('or new directory for -o." >&2\n    exit 2', 'or new directory for -o." >&2\n    exit 0', 1)], '', ''),
    ('m25', 'unmarked non-empty dir refused only if it has out/', [(r'if [ ! -f "$BUNDLE/$MARKER" ]; then', r'if [ ! -f "$BUNDLE/$MARKER" ] && [ -d "$BUNDLE/out" ]; then', 1)], '', ''),
    ('m26', '-o naming a regular file no longer refused', [(r'if [ -e "$BUNDLE" ] && [ ! -d "$BUNDLE" ]; then', r'if false; then', 1)], '', ''),
    ('m27', 'skip list drops node_modules', [(r'SKIP_DIRS=".git node_modules ', r'SKIP_DIRS=".git ', 1)], '', ''),
    ('m28', 'skip list drops .git', [(r'SKIP_DIRS=".git ', r'SKIP_DIRS="', 1)], '', ''),
    ('m29', 'skip list drops vendor', [(r'node_modules vendor dist', r'node_modules dist', 1)], '', ''),
    ('m30', 'secret-scan no longer skips node_modules', [(r'SECRET_EX="--exclude-dir=.git --exclude-dir=node_modules ', r'SECRET_EX="--exclude-dir=.git ', 1)], '', ''),
    ('m31', 'file-count counts newlines', [(r"""probe file-count performance "find . $PRUNE -type f -print0 | tr -dc '\\000' | wc -c""", r"""probe file-count performance "find . $PRUNE -type f -print | wc -l""", 1)], '', ''),
    ('m32', 'test-file-count counts newlines', [(r"""-name '*_test.sh' \\) -print0 | tr -dc '\\000' | wc -c""", r"""-name '*_test.sh' \\) -print | wc -l""", 1)], '', ''),
    ('m33', 'test-file-count loses *test*.php', [(r"-name '*test*.php' -o ", '', 1)], '', ''),
    ('m34', 'test-inventory loses tests/', [(r'-o -name tests ', '', 1)], '', ''),
    ('m35', 'largest-files back to ls -l | awk', [(r'-exec $STAT_SIZE {} + | sort -rn', r"-exec ls -l {} + | awk '{print \$5, \$9}' | sort -rn", 1)], '', ''),
    ('m36', 'largest-files sorted ascending', [(r'{} + | sort -rn" 0 15', r'{} + | sort -n" 0 15', 1)], '', ''),
    ('m37', 'repo-size measures nothing', [(r'du -sh . | cut -f1', r'du -sh /nonexistent-cba | cut -f1', 1)], '', ''),
    ('m38', 'secret-scan no longer looks for password/passwd', [(r"grep -rIniE '((password|passwd|secret|", r"grep -rIniE '((secret|", 1)], '', ''),
    ('m39', 'secret-scan minimum literal length 6 -> 16', [(r'{6,}|[a-z]', r'{16,}|[a-z]', 1)], '', ''),
    ('m40', 'include globs expanded without set -f', [(r'''set -f; for _g in $SECRET_GLOBS; do SECRET_INC="$SECRET_INC --include='$_g'"; done; set +f''', r'''for _g in $SECRET_GLOBS; do SECRET_INC="$SECRET_INC --include='$_g'"; done''', 1)], '', ''),
    ('m41', 'secret-scan stops reading *.env* and *.php', [('*.env* ', '', 1), ('*.php ', '', 1)], '', ''),
    ('m42', 'minified files, maps and lockfiles scanned again', [('FILE_EX=\'--exclude="*.min.js" --exclude="*.min.css" --exclude="*.map" --exclude="*-lock.json" --exclude="*.lock"\'\n', "FILE_EX=''\n", 1)], '', ''),
    ('m43', 'empty secret-scan note reverts to ran clean', [(r'"the pattern matched nothing in the file types listed in env.txt.', r'"" #"', 1)], '', ''),
    ('m45', 'composer-audit findings exits not expected', [(r"--no-plugins --no-scripts' '0 1 2'", r"--no-plugins --no-scripts' '0'", 1)], '', ''),
    ('m45b', 'govulncheck findings exit not expected', [(r"govulncheck ./...' '0 3'", r"govulncheck ./...' '0'", 1)], '', ''),
    ('m45c', 'cargo-audit findings exit not expected', [(r"'cargo-audit audit' '0 1'", r"'cargo-audit audit' '0'", 1)], '', ''),
    ('m45d', 'bundler-audit findings exit not expected', [(r"'bundler-audit check --update' '0 1'", r"'bundler-audit check --update' '0'", 1)], '', ''),
    ('m46', 'git-log asks for 40, so truncation is never visible', [(r'log --oneline -41 -- .', r'log --oneline -40 -- .', 1)], '', ''),
    ('m47', 'git detection back to [ -d .git ]', [(r'if has git && ( cd "$TARGET" && $GIT rev-parse --is-inside-work-tree ) >/dev/null 2>&1; then', r'if has git && [ -d "$TARGET/.git" ]; then', 1)], '', ''),
    ('m48', 'git scope always reports subdirectory', [(r'if [ "$GITROOT" = "$TARGET" ]; then GITSCOPE="repo root"', r'if false; then GITSCOPE="repo root"', 1)], '', ''),
    ('m49', 'summary stderr WARN removed', [(r'[ "$E" -gt 0 ] && echo', r'[ "$E" -lt 0 ] && echo', 1)], '', ''),
    ('m50', 'summary no-timeout WARN removed', [(r'|| echo "  WARN    no timeout binary', r'|| true "  WARN    no timeout binary', 1)], 'no-timeout', ''),
    ('m51', 'env.txt claims enforcement when no binary exists', [(r'echo "timeout:    NONE ENFORCED — ${PTIMEOUT}s requested', r'echo "timeout:    ${PTIMEOUT}s per probe — ${PTIMEOUT}s requested', 1)], 'no-timeout', ''),
    ('m52', 'bash -n exit 2 treated as failure', [(r'bash -n \"\$f\" 2>&1; [ \$? -le 2 ]', r'bash -n \"\$f\" 2>&1; [ \$? -le 1 ]', 1)], 'no-shellcheck', ''),
    ('m53', 'bash -n on an unreadable file accepted', [(r'bash -n \"\$f\" 2>&1; [ \$? -le 2 ]', r'bash -n \"\$f\" 2>&1; [ \$? -le 255 ]', 1)], 'no-shellcheck non-root', ''),
    ('m54', 'shellcheck exit 2 accepted', [(r'shellcheck -f gcc \"\$@\"; [ \$? -le 1 ]', r'shellcheck -f gcc \"\$@\"; [ \$? -le 2 ]', 1)], '', ''),
    ('m55', 'php -l exit 1 accepted', [(r'case \$? in 0|255) ;;', r'case \$? in 0|1|255) ;;', 1)], '', ''),
    ('m56', 'host-container gate removed', [(r'if [ "$HOST_CONTAINERS" -eq 1 ] && has docker; then', r'if has docker; then', 1)], '', ''),
    ('m57', 'db-clients no longer checks that exec works', [(r'if docker exec "$c" true >/dev/null; then', r'if true; then', 1)], '', ''),
    ('m58', 'placeholder filter stops dropping changeme', [(r'|placeholder|changeme|', r'|placeholder|', 1)], '', ''),

    # --- the fixes made after the v1.3.0 audit
    ('n01', 'toolchains run by default', [(r'RUN_TOOLCHAINS=0; PTIMEOUT', r'RUN_TOOLCHAINS=1; PTIMEOUT', 1)], '', ''),
    ('n02', 'cargo audit through cargo, so aliases resolve', [(r"elif has cargo-audit; then probe cargo-audit supply-chain 'cargo-audit audit'", r"elif has cargo; then probe cargo-audit supply-chain 'cargo audit'", 1)], '', ''),
    ('n03', 'git config overrides removed', [(r'GIT="git -c core.fsmonitor=false -c log.showSignature=false"', r'GIT="git"', 1)], '', ''),
    ('n03b', 'log.showSignature override removed', [(r'GIT="git -c core.fsmonitor=false -c log.showSignature=false"', r'GIT="git -c core.fsmonitor=false"', 1)], '', ''),
    ('n03c', 'core.fsmonitor override removed', [(r'GIT="git -c core.fsmonitor=false -c log.showSignature=false"', r'GIT="git -c log.showSignature=false"', 1)], '', ''),
    ('n04', 'git-status runs by default', [(r'if [ "$RUN_TOOLCHAINS" -eq 1 ]; then probe git-status', r'if true; then probe git-status', 1)], '', ''),
    ('n05', 'composer plugins and scripts allowed', [(r" --no-plugins --no-scripts'", r"'", 1)], '', ''),
    ('n06', 'npm registry not pinned', [(r" --registry=https://registry.npmjs.org/'", r"'", 1)], '', ''),
    ('n07', 'pip-audit audits the environment again', [(r"'pip-audit -r requirements.txt -f json", r"'pip-audit -f json", 1)], '', ''),
    ('n08', 'govulncheck may switch toolchains', [(r"'GOTOOLCHAIN=local govulncheck", r"'govulncheck", 1)], '', ''),
    ('n09', 'bundler-audit through bundle', [(r"elif has bundler-audit; then probe bundler-audit supply-chain 'bundler-audit check --update'", r"elif has bundle; then probe bundler-audit supply-chain 'bundle audit check --update'", 1)], '', ''),
    ('n10', 'umask removed', [('umask 077\n', '\n', 1)], '', ''),
    ('n11', 'bundle directory not made private', [('chmod 700 "$BUNDLE"\n', '\n', 1)], '', ''),
    ('n12', 'default bundle name predictable again', [(r'BUNDLE=$(mktemp -d "${TMPDIR:-/tmp}/codebase-audit-$(basename "$TARGET")-$(date +%Y%m%d-%H%M%S).XXXXXX")', r'BUNDLE="${TMPDIR:-/tmp}/codebase-audit-$(basename "$TARGET")-$(date +%Y%m%d-%H%M%S)"; mkdir -p "$BUNDLE"', 1)], '', ''),
    ('n13', 'bundle inside the target accepted', [(r'"$TARGET"/*) echo "refusing: bundle', r'"$TARGET"/nomatch/*) echo "refusing: bundle', 1)], '', ''),
    ('n14', 'bundle path symlinks not resolved', [(r'''printf '%s%s\n' "$(cd -P -- "$_p" >/dev/null && pwd -P)" "$_rest"''', r'''printf '%s%s\n' "$_p" "$_rest"''', 1)], '', ''),
    ('n15', 'foreign-owned -o accepted', [(r'[ -d "$BUNDLE" ] && [ ! -O "$BUNDLE" ]', r'[ -d "$BUNDLE" ] && false', 1)], 'root', ''),
    ('n16', 'CDPATH honoured', [('unset CDPATH\n', '\n', 1)], '', ''),
    ('n17', 'secret-scan filter decides the exit again', [(r"""[(])' || [ \$? -eq 1 ]; }" '0 1' 40""", r"""[(])'; }" '0 1' 40""", 1)], 'non-root', ''),
    ('n17b', 'route-tables filter decides the exit again', [(r"""(node_modules|vendor|test|spec)' || [ \$? -eq 1 ]; }""", r"""(node_modules|vendor|test|spec)'; }""", 1)], 'non-root', ''),
    ('n17c', 'health-endpoints filter decides the exit again', [(r"""--include='*.go' $GREP_EX . | { grep -viE '(node_modules|vendor)' || [ \$? -eq 1 ]; }""", r"""--include='*.go' $GREP_EX . | { grep -viE '(node_modules|vendor)'; }""", 1)], 'non-root', ''),
    ('n17d', 'telemetry filter decides the exit again', [(r"""--include='*.y*ml' $GREP_EX . | { grep -viE '(node_modules|vendor)' || [ \$? -eq 1 ]; }""", r"""--include='*.y*ml' $GREP_EX . | { grep -viE '(node_modules|vendor)'; }""", 1)], 'non-root', ''),
    ('n17e', 'swallowed-exceptions filters decide the exit again', [(r"""(node_modules|vendor|test)' || [ \$? -eq 1 ]; }""", r"""(node_modules|vendor|test)'; }""", 1), (r"""[[:space:]]*\\}' || [ \$? -eq 1 ]; }""", r"""[[:space:]]*\\}'; }""", 1)], 'non-root', ''),
    ('n19', 'empty with stderr says ran clean', [(r'_status="empty"; _note="produced no output, but wrote stderr', r'_status="empty"; _note="ran clean, produced no output', 1)], '', ''),
    ('n20', 'no-report note drops the tool message', [(r'''_said=$(grep -oE '"(message|code|summary)"''', r'''_said=$(true '"(message|code|summary)"''', 1), (r'''[ -n "$_said" ] || _said=$(cat "$_out" "$_err"''', r'''[ -n "$_said" ] || _said=$(true "$_out" "$_err"''', 1)], '', ''),
    ('n21', 'leading zeros not stripped from --timeout', [('''PTIMEOUT=$(printf '%s' "$PTIMEOUT" | sed 's/^0*//'); PTIMEOUT="${PTIMEOUT:-0}"\n''', '\n', 1)], '', ''),
    ('n22', '--timeout length unchecked', [(r'[ "${#PTIMEOUT}" -le 6 ]', r'[ "${#PTIMEOUT}" -le 99 ]', 1)], '', ''),
    ('n23', 'db-clients ignores a failed docker ps', [(r'cs=$(docker ps --format "{{.Names}}") || exit 1;', r'cs=$(docker ps --format "{{.Names}}") || true;', 1)], '', ''),
    ('n24', 'db-clients exit ignores refused execs', [(r'rc=1; fi; done; exit $rc', r'rc=1; fi; done; exit 0', 1)], '', ''),
    ('n25', 'skip list loses generated trees', [(r' dist build coverage .venv venv __pycache__ third_party bower_components target jquery"', r'"', 1)], '', ''),
    ('n25b', 'skip list loses target', [(r' bower_components target jquery"', r' bower_components jquery"', 1)], '', ''),
    ('n26', 'secret-scan skips build/ and dist/ again', [(r'$SECRET_INC $SECRET_EX .', r'$SECRET_INC $GREP_EX .', 1)], '', ''),
    ('n27', 'secret-scan case-sensitive again', [(r"grep -rIniE '((password", r"grep -rInE '((password", 1)], '', ''),
    ('n28', 'URL credentials not matched', [("""|[a-z][a-z0-9+.-]*://[^/:@[:space:]\\"'\\"'\\"']+:[^/@[:space:]\\"'\\"'\\"']{6,}@)'""", ")'", 1)], '', ''),
    ('n29', 'call-valued assignments reported', [("""|(password|passwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key)([_-]?key|[_-][a-z0-9_-]*)?[\\"'\\"'\\"']?[[:space:]]*(:|=>?)[[:space:]]*[A-Za-z_][A-Za-z0-9_.]*[(])'""", ")'", 1)], '', ''),
    ('n30', 'placeholder filter reads the path again', [(r"grep -viE '^[^:]*:[0-9]+:.*(example", r"grep -viE '(example", 1)], '', ''),
    ('n31', 'plural keys match again', [(r"""((password|passwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key)([_-]?key|[_-][a-z0-9_-]*)?([""", r"""((password|passwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key)[a-z0-9_-]*([""", 1)], '', ''),
    ('n32', 'a bare comma separates key and value again', [("""|[\\"'\\"'\\"'][[:space:]]*,[[:space:]]*[\\"'\\"'\\"'])[A-Za-z0-9""", "|[[:space:]]*,[[:space:]]*)[A-Za-z0-9", 1)], '', ''),
    ('n33', 'dockerfiles finds Dockerfile* only', [(r"-o -name '*.Dockerfile' -o -name '*.dockerfile' -o -name 'Containerfile*' ", '', 1)], '', ''),
    ('n34', 'dockerfile-fetches reads Dockerfile* only', [(r'''DOCKER_INC="--include='Dockerfile*' --include='*.Dockerfile' --include='*.dockerfile' --include='Containerfile*'"''', r'''DOCKER_INC="--include='Dockerfile*'"''', 1)], '', ''),
    ('n35', 'FROM :latest not flagged', [(r'|^[[:space:]]*FROM([[:space:]]+--[^[:space:]]+)*[[:space:]]+[^[:space:]]+:latest([[:space:]]|\$)', '', 1)], '', ''),
    ('n35b', 'untagged FROM not flagged', [(r'|^[[:space:]]*FROM([[:space:]]+--[^[:space:]]+)*[[:space:]]+[^:@[:space:]]+([[:space:]]+AS[[:space:]]+[^[:space:]]+)?[[:space:]]*\$)', ')', 1)], '', ''),
    ('n35c', 'Dockerfile instructions case-sensitive', [(r"grep -rHniE '(git clone", r"grep -rHnE '(git clone", 1)], '', ''),
    ('n36', 'gated rows filed n/a', [(r'''printf '%s\t%s\terror\t-\t0\t0\tno\t-\t%s\n' "$1" "$2"''', r'''printf '%s\t%s\tn/a\t-\t0\t0\tno\t-\t%s\n' "$1" "$2"''', 1)], '', ''),
    ('n37', 'env.txt does not record toolchains withheld', [(r'echo "toolchains: NOT RUN', r'echo "toolchains: run', 1)], '', ''),
    ('n38', 'git-staged compares the work tree, running filters', [(r'$GIT diff-index --cached --name-status HEAD', r'$GIT diff-index --name-status HEAD', 1)], '', ''),
]

# One mutant per probe: its command becomes `true`. A probe no test notices going
# silent is a probe whose output nothing pins.
PROBES = [
    'git-remotes', 'git-log', 'git-commit-count', 'git-authors', 'git-status', 'git-staged', 'git-untracked',
    'git-tracked', 'git-tags', 'git-submodules', 'git-churn', 'composer-manifest', 'composer-audit',
    'npm-manifest', 'npm-audit', 'pip-audit', 'go-vulncheck', 'cargo-audit', 'bundler-audit', 'dockerfiles',
    'dockerfile-fetches', 'compose-files', 'docker-ps', 'db-clients', 'secret-scan', 'env-files',
    'published-ports', 'route-tables', 'route-verbs', 'lint-config', 'lang-census', 'php-syntax', 'shell-lint',
    'shell-syntax-only', 'test-inventory', 'test-file-count', 'ci-config', 'ci-badges', 'health-endpoints',
    'log-surface', 'telemetry', 'swallowed-exceptions', 'repo-size', 'largest-files', 'file-count',
    'license-files', 'dep-licenses',
]
ANCHOR = '  _out="$BUNDLE/out/$_name.txt";'
for p in PROBES:
    M.append(('s-' + p, p + ' measures nothing', [(ANCHOR, '  [ "$_name" = "%s" ] && _cmd=true\n%s' % (p, ANCHOR), 1)],
              'no-shellcheck' if p == 'shell-syntax-only' else '', ''))


def build(out):
    src = open(os.path.join(SCRIPTS, 'probe.sh')).read()
    os.makedirs(out, exist_ok=True)
    index = []
    for mid, desc, subs, req, equiv in M:
        s = src
        for old, new, count in subs:
            n = s.count(old)
            if n != count:
                sys.exit('%s: expected %d occurrence(s), found %d: %r' % (mid, count, n, old[:90]))
            s = s.replace(old, new)
        if s == src:
            sys.exit('%s: substitution changed nothing' % mid)
        d = os.path.join(out, mid)
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, 'probe.sh'), 'w').write(s)
        shutil.copy(os.path.join(SCRIPTS, 'test_probe.sh'), d)
        if subprocess.call(['bash', '-n', os.path.join(d, 'probe.sh')]) != 0:
            sys.exit('%s: mutant is not valid bash' % mid)
        index.append('\t'.join([mid, req or '-', equiv or '-', desc]))
    open(os.path.join(out, 'index.tsv'), 'w').write('\n'.join(index) + '\n')
    print('%d mutants in %s' % (len(index), out))


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == 'build':
        build(sys.argv[2])
    elif len(sys.argv) == 2 and sys.argv[1] == 'list':
        for mid, desc, _, req, equiv in M:
            print('\t'.join([mid, req or '-', equiv or '-', desc]))
    else:
        sys.exit(__doc__)
