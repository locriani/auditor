"""Nested manifest discovery, and the report checks each scanner row must pass."""

from __future__ import annotations

from pathlib import Path

from conftest import RunProbe

XCODE_PINS = "App/App.xcodeproj/project.xcworkspace/xcshareddata/swiftpm"


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _stub(bin_dir: Path, name: str, body: str) -> Path:
    """A stand-in that logs `$PWD $*` to <name>.calls, then runs `body`."""
    calls = bin_dir / f"{name}.calls"
    stub = bin_dir / name
    stub.write_text(f"#!/bin/sh\necho \"$PWD $*\" >> '{calls}'\n{body}\n", encoding="utf-8")
    stub.chmod(0o755)
    return calls


def _probes(manifest: object) -> set[str]:
    return {r["probe"] for r in manifest.rows()}  # type: ignore[attr-defined]


def test_nested_manifests_are_projects(temp_target: Path, run_probe: RunProbe) -> None:
    # npm workspace: the root lock pins packages/web, which is not a project of its own
    _write(temp_target, "package.json", '{"workspaces": ["packages/*"]}\n')
    _write(temp_target, "package-lock.json", "{}\n")
    _write(temp_target, "packages/web/package.json", '{"name": "web"}\n')
    # a separate npm project with its own lock
    _write(temp_target, "tools/cli/package.json", '{"name": "cli"}\n')
    _write(temp_target, "tools/cli/package-lock.json", "{}\n")
    # cargo workspace member under the root lock
    _write(temp_target, "Cargo.toml", "[workspace]\n")
    _write(temp_target, "Cargo.lock", "version = 3\n")
    _write(temp_target, "crates/core/Cargo.toml", "[package]\nname = 'core'\n")
    _write(temp_target, "services/api/go.mod", "module api\n")
    _write(temp_target, "services/api/go.sum", "")
    _write(temp_target, f"{XCODE_PINS}/Package.resolved", '{"pins": []}\n')
    _write(temp_target, "ios/Podfile.lock", "PODS:\n")
    _write(temp_target, "node_modules/left-pad/package.json", "{}\n")

    manifest = run_probe(temp_target)
    probes = _probes(manifest)

    assert {
        "npm-audit",
        "npm-audit@tools/cli",
        "cargo-audit",
        "go-vulncheck@services/api",
    } <= probes
    assert f"swift-audit@{XCODE_PINS}" in probes
    assert "cocoapods-audit@ios" in probes
    assert not any("packages/web" in p or "crates/core" in p for p in probes)
    assert not any("node_modules" in p for p in probes)
    assert "dep-licenses@tools/cli" in probes
    assert manifest.status("npm-audit@tools/cli") == "error"  # gated
    assert '"name": "cli"' in manifest.out_content("npm-manifest@tools/cli")
    assert "dependency-audit" not in probes


def test_nested_project_scans_in_its_own_directory(
    temp_target: Path, mock_bin_dir: Path, run_probe: RunProbe
) -> None:
    _write(temp_target, f"{XCODE_PINS}/Package.resolved", '{"pins": []}\n')
    calls = _stub(mock_bin_dir, "trivy", 'printf \'{"SchemaVersion": 2, "Results": []}\'')

    manifest = run_probe(temp_target, "--run-toolchains")
    probe = f"swift-audit@{XCODE_PINS}"
    assert manifest.status(probe) == "ok"
    assert '"Results"' in manifest.out_content(probe)
    assert str((temp_target / XCODE_PINS / "Package.resolved").resolve()) in calls.read_text()


def test_composer_audits_the_lock_without_the_targets_config(
    temp_target: Path, mock_bin_dir: Path, run_probe: RunProbe
) -> None:
    # config.policy.advisories.ignore hid all 14 advisories from real composer 2.10.3
    _write(
        temp_target,
        "composer.json",
        '{"require": {"guzzlehttp/guzzle": "7.4.0"},'
        ' "config": {"policy": {"advisories": {"ignore": {"guzzlehttp/guzzle": "x"}}}}}\n',
    )
    _write(temp_target, "composer.lock", '{"packages": []}\n')
    seen = mock_bin_dir / "composer.json.seen"
    calls = _stub(
        mock_bin_dir,
        "composer",
        f"cp composer.json '{seen}'\n"
        'printf \'{"advisories": {"guzzlehttp/guzzle": [{}]}, "abandoned": []}\'\nexit 1',
    )

    manifest = run_probe(temp_target, "--run-toolchains")
    assert manifest.status("composer-audit") == "ok"
    cwd, args = calls.read_text().split(" ", 1)
    assert "--locked" in args.split()
    assert Path(cwd).resolve() != temp_target.resolve()
    assert '"config"' not in seen.read_text()
    assert "guzzlehttp/guzzle" in seen.read_text()


def test_composer_failure_is_not_a_report(
    temp_target: Path, mock_bin_dir: Path, run_probe: RunProbe
) -> None:
    _write(temp_target, "composer.json", "{}\n")
    _write(temp_target, "composer.lock", "{broken\n")
    _stub(mock_bin_dir, "composer", "echo 'In JsonFile.php line 398:' >&2\nexit 1")

    manifest = run_probe(temp_target, "--run-toolchains")
    assert manifest.status("composer-audit") == "error"


def test_composer_refuses_without_lock(
    temp_target: Path, mock_bin_dir: Path, run_probe: RunProbe
) -> None:
    _write(temp_target, "composer.json", "{}\n")
    calls = _stub(mock_bin_dir, "composer", "exit 0")

    manifest = run_probe(temp_target, "--run-toolchains")
    assert manifest.status("composer-audit") == "n/a"
    assert not calls.exists()


# Real govulncheck 1.8.0 -format json: a scan that loaded packages carries SBOM; a go.mod
# that fails to load exits 1 and still prints the config header.
GOVULN_CONFIG = '{"config": {"scanner_name": "govulncheck"}}'


def test_govulncheck_report_needs_a_package_load(
    temp_target: Path, mock_bin_dir: Path, run_probe: RunProbe
) -> None:
    _write(temp_target, "go.mod", "module x\n")
    _stub(mock_bin_dir, "govulncheck", f"printf '%s' '{GOVULN_CONFIG}'\nexit 1")
    manifest = run_probe(temp_target, "--run-toolchains")
    assert manifest.status("go-vulncheck") == "error"
    assert "printed no report" in manifest.note("go-vulncheck")

    _stub(
        mock_bin_dir,
        "govulncheck",
        '[ "$1 $2" = "-format json" ] || exit 9\n'
        f"printf '%s' '{GOVULN_CONFIG}{{\"SBOM\": {{}}}}{{\"finding\": {{}}}}'",
    )
    manifest = run_probe(temp_target, "--run-toolchains")
    assert manifest.status("go-vulncheck") == "ok"


def test_bundler_audit_ignores_the_targets_config(
    temp_target: Path, mock_bin_dir: Path, run_probe: RunProbe
) -> None:
    _write(temp_target, "Gemfile", "gem 'rack', '2.0.0'\n")
    _write(temp_target, "Gemfile.lock", "GEM\n  specs:\n    rack (2.0.0)\n")
    _write(temp_target, ".bundler-audit.yml", "---\nignore:\n  - CVE-2018-16471\n")
    seen = mock_bin_dir / "config.seen"
    _stub(
        mock_bin_dir,
        "bundler-audit",
        'while [ $# -gt 0 ]; do [ "$1" = --config ] && cp "$2" '
        f"'{seen}'; shift; done\n"
        'printf \'{"version": "0.9.3", "results": [{}]}\'\nexit 1',
    )

    manifest = run_probe(temp_target, "--run-toolchains")
    assert manifest.status("bundler-audit") == "ok"
    assert seen.read_text() == "--- {}\n"


def test_bundler_audit_refuses_an_unreadable_lock(
    temp_target: Path, mock_bin_dir: Path, run_probe: RunProbe
) -> None:
    # real bundler-audit 0.9.3 reports a garbage Gemfile.lock as "No vulnerabilities found"
    _write(temp_target, "Gemfile", "gem 'rack'\n")
    _write(temp_target, "Gemfile.lock", "garbage {{\n")
    calls = _stub(mock_bin_dir, "bundler-audit", "printf '{\"results\": []}'")

    manifest = run_probe(temp_target, "--run-toolchains")
    assert manifest.status("bundler-audit") == "n/a"
    assert "no specs:" in manifest.note("bundler-audit")
    assert not calls.exists()


def test_bundler_audit_failure_is_not_a_report(
    temp_target: Path, mock_bin_dir: Path, run_probe: RunProbe
) -> None:
    # exit 1 is also bundler-audit's "vulnerable" code, so only the report tells them apart
    _write(temp_target, "Gemfile", "gem 'rack'\n")
    _write(temp_target, "Gemfile.lock", "GEM\n  specs:\n    rack (2.0.0)\n")
    _stub(mock_bin_dir, "bundler-audit", "echo 'Failed to update advisory db' >&2\nexit 1")

    manifest = run_probe(temp_target, "--run-toolchains")
    assert manifest.status("bundler-audit") == "error"


def test_nested_npm_project_audits_in_its_own_directory(
    temp_target: Path, mock_bin_dir: Path, run_probe: RunProbe
) -> None:
    _write(temp_target, "tools/cli/package.json", '{"name": "cli"}\n')
    _write(temp_target, "tools/cli/package-lock.json", "{}\n")
    calls = _stub(mock_bin_dir, "npm", "printf '{\"auditReportVersion\": 2}'")

    manifest = run_probe(temp_target, "--run-toolchains")
    assert manifest.status("npm-audit@tools/cli") == "ok"
    audit = next(c for c in calls.read_text().splitlines() if " audit " in c)
    assert Path(audit.split(" ", 1)[0]).resolve() == (temp_target / "tools/cli").resolve()
