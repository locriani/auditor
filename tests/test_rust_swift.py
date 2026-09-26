"""Tests for Rust and Swift target support across the probe axes."""

from __future__ import annotations

from pathlib import Path

from conftest import RunProbe


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_rust_target(temp_target: Path, run_probe: RunProbe) -> None:
    _write(temp_target, "Cargo.toml", '[package]\nname = "svc"\n\n[dependencies]\naxum = "0.7"\n')
    _write(temp_target, "clippy.toml", "")
    _write(
        temp_target,
        "src/main.rs",
        "use tracing::info;\n"
        'fn main() {\n    let app = Router::new().route("/healthz", get(ok));\n'
        "    let n = parse().unwrap();\n    let _ = save(n);\n"
        "    unsafe { ptr.read() };\n}\n"
        "#[cfg(test)]\nmod tests {}\n",
    )
    _write(temp_target, "src/lib.rs", "pub fn f() {}\n")
    _write(temp_target, "tests/api.rs", "fn helper() { x.unwrap() }\n")
    _write(temp_target, "target/debug/build/gen.rs", "fn g() { a.unwrap(); }\n")

    manifest = run_probe(temp_target)

    assert manifest.status("cargo-manifest") == "ok"
    assert 'axum = "0.7"' in manifest.out_content("cargo-manifest")
    assert manifest.status("cargo-audit") == "error"
    assert "./clippy.toml" in manifest.out_content("lint-config")

    markers = manifest.out_content("rust-markers")
    # tests/ and target/ are excluded, so exactly one unwrap counts
    assert "      1 .unwrap()" in markers
    assert "      1 unsafe" in markers
    assert "      1 let _ = (result discarded)" in markers

    # main.rs (inline #[cfg(test)]) and tests/api.rs; lib.rs is not a test file
    assert manifest.out_content("test-file-count").strip() == "2"
    assert "./src/main.rs" in manifest.out_content("route-tables")
    assert "./src/main.rs" in manifest.out_content("health-endpoints")
    assert "tracing::" in manifest.out_content("log-surface")
    assert manifest.status("swift-markers") == "n/a"


def test_swift_target(temp_target: Path, run_probe: RunProbe) -> None:
    _write(temp_target, "Package.swift", "// swift-tools-version:5.9\nimport PackageDescription\n")
    _write(temp_target, "Package.resolved", '{"pins": [{"identity": "vapor"}]}\n')
    _write(temp_target, ".swiftlint.yml", "disabled_rules: []\n")
    _write(temp_target, "Config/Release.xcconfig", "API_KEY = sk9f8a7b6c5d4e\n")
    _write(
        temp_target,
        "Sources/App/routes.swift",
        "import OSLog\n"
        'func routes(_ app: Application) {\n    app.get("hello") { _ in "hi" }\n'
        "    let d = try? load()\n    let v = x as! Int\n"
        "    do { try save() } catch {}\n"
        "    do {\n        try run()\n    } catch {\n    }\n}\n",
    )
    _write(
        temp_target,
        "Sources/App/Daemon.swift",
        "// libdispatch / runtime sets signals\n"
        "func handle() -> Int {\n    do { return try answer() } catch { return -1 }\n}\n",
    )
    _write(temp_target, "Tests/AppTests/RoutesTests.swift", "let y = try! load()\n")
    _write(temp_target, ".build/checkouts/vapor/Sources/V.swift", "let z = try! a()\n")
    _write(temp_target, "Pods/Alamofire/AF.swift", "let z = try! a()\n")

    manifest = run_probe(temp_target)

    assert manifest.status("swiftpm-manifest") == "ok"
    assert manifest.status("swiftpm-resolved") == "ok"
    assert "vapor" in manifest.out_content("swiftpm-resolved")
    assert manifest.status("swift-audit") == "error"  # gated without --run-toolchains
    assert "dependency-audit" not in {r["probe"] for r in manifest.rows()}
    assert "./.swiftlint.yml" in manifest.out_content("lint-config")
    assert "Release.xcconfig" in manifest.out_content("secret-scan")

    markers = manifest.out_content("swift-markers")
    # the test file, .build/ and Pods/ are excluded
    assert "try!" not in markers
    assert "      1 try? (error discarded)" in markers
    assert "      1 as!" in markers

    assert "./Tests" in manifest.out_content("test-inventory")
    assert "./Tests/AppTests" in manifest.out_content("test-inventory")
    assert manifest.out_content("test-file-count").strip() == "1"
    assert "./Sources/App/routes.swift" in manifest.out_content("route-tables")
    assert "Daemon.swift" not in manifest.out_content("route-tables")  # "libdispatch /"
    assert "OSLog" in manifest.out_content("log-surface")

    swallowed = manifest.out_content("swallowed-exceptions")
    assert "routes.swift:6:" in swallowed  # one-line catch {}
    assert "routes.swift:10:" in swallowed  # catch { / }
    assert "Daemon.swift" not in swallowed  # one-line catch with a body, then the func's }
    assert manifest.status("rust-markers") == "n/a"


def test_cocoapods_lockfile_alone_is_a_manifest(temp_target: Path, run_probe: RunProbe) -> None:
    _write(temp_target, "Podfile.lock", "PODS:\n  - Alamofire (5.8.0)\n")
    manifest = run_probe(temp_target)
    assert "Alamofire (5.8.0)" in manifest.out_content("cocoapods-lockfile")
    assert manifest.status("cocoapods-audit") == "error"  # gated without --run-toolchains
    assert "swift-audit" not in {r["probe"] for r in manifest.rows()}


def test_cargo_audit_error_is_not_a_report(
    temp_target: Path, mock_bin_dir: Path, run_probe: RunProbe
) -> None:
    _write(temp_target, "Cargo.toml", "[package]\nname = 'svc'\n")
    _write(temp_target, "Cargo.lock", "version = 3\n")
    stub = mock_bin_dir / "cargo-audit"
    stub.write_text(
        "#!/bin/sh\necho 'error: not found: Couldn'\"'\"'t load Cargo.lock' >&2\nexit 1\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)

    manifest = run_probe(temp_target, "--run-toolchains")
    assert manifest.status("cargo-audit") == "error"
    assert "printed no report" in manifest.note("cargo-audit")


def test_cargo_audit_findings_is_ok(
    temp_target: Path, mock_bin_dir: Path, run_probe: RunProbe
) -> None:
    _write(temp_target, "Cargo.toml", "[package]\nname = 'svc'\n")
    _write(temp_target, "Cargo.lock", "version = 3\n")
    stub = mock_bin_dir / "cargo-audit"
    stub.write_text(
        "#!/bin/sh\n"
        '[ "$1 $2" = "audit --json" ] || exit 9\n'
        # shape from real cargo-audit 0.22.2 --json
        'printf \'{"database":{},"vulnerabilities":{"found":true,"count":1,"list":[]}}\'\n'
        "exit 1\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)

    manifest = run_probe(temp_target, "--run-toolchains")
    assert manifest.status("cargo-audit") == "ok"


def test_cargo_audit_refuses_without_lockfile(
    temp_target: Path, mock_bin_dir: Path, run_probe: RunProbe
) -> None:
    _write(temp_target, "Cargo.toml", "[package]\nname = 'svc'\n")
    footprint = mock_bin_dir / "cargo-audit.called"
    stub = mock_bin_dir / "cargo-audit"
    stub.write_text(f"#!/bin/sh\ntouch '{footprint}'\n", encoding="utf-8")
    stub.chmod(0o755)

    manifest = run_probe(temp_target, "--run-toolchains")
    assert manifest.status("cargo-audit") == "n/a"
    assert "no Cargo.lock" in manifest.note("cargo-audit")
    assert not footprint.exists(), "cargo-audit ran without a lockfile"


# Shape from real `cargo metadata --format-version 1 --locked` (cargo 1.9x): the target's own
# crate is a workspace member; license is an SPDX string or null beside license_file.
CARGO_METADATA = (
    '{"packages": ['
    '{"name": "svc", "version": "0.1.0", "id": "path+file:///t#svc@0.1.0",'
    ' "license": "MIT", "license_file": null},'
    '{"name": "serde", "version": "1.0.229", "id": "registry+x#serde@1.0.229",'
    ' "license": "MIT OR Apache-2.0", "license_file": null},'
    '{"name": "ring", "version": "0.16.20", "id": "registry+x#ring@0.16.20",'
    ' "license": null, "license_file": "LICENSE"},'
    '{"name": "mystery", "version": "0.0.1", "id": "registry+x#mystery@0.0.1",'
    ' "license": null, "license_file": null}'
    '], "workspace_members": ["path+file:///t#svc@0.1.0"]}'
)


def _cargo_stub(bin_dir: Path, stdout: str) -> Path:
    footprint = bin_dir / "cargo.called"
    stub = bin_dir / "cargo"
    stub.write_text(
        f"#!/bin/sh\ntouch '{footprint}'\n"
        '[ "$1 $2 $3 $4" = "metadata --format-version 1 --locked" ] || exit 9\n'
        f"printf '%s' '{stdout}'\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return footprint


def test_cargo_licenses(temp_target: Path, mock_bin_dir: Path, run_probe: RunProbe) -> None:
    _write(temp_target, "Cargo.toml", "[package]\nname = 'svc'\n")
    _write(temp_target, "Cargo.lock", "version = 3\n")
    _cargo_stub(mock_bin_dir, CARGO_METADATA)

    manifest = run_probe(temp_target, "--run-toolchains")
    assert manifest.status("cargo-licenses") == "ok"
    assert manifest.out_content("cargo-licenses").splitlines() == [
        "MIT OR Apache-2.0\tserde 1.0.229",
        "NO LICENSE DECLARED\tmystery 0.0.1",
        "license-file: LICENSE\tring 0.16.20",
    ]


def test_cargo_licenses_refuses_without_lockfile(
    temp_target: Path, mock_bin_dir: Path, run_probe: RunProbe
) -> None:
    _write(temp_target, "Cargo.toml", "[package]\nname = 'svc'\n")
    footprint = _cargo_stub(mock_bin_dir, CARGO_METADATA)

    manifest = run_probe(temp_target, "--run-toolchains")
    assert manifest.status("cargo-licenses") == "n/a"
    assert not footprint.exists(), "cargo ran without a lockfile"


def test_cargo_licenses_garbage_is_not_a_license_list(
    temp_target: Path, mock_bin_dir: Path, run_probe: RunProbe
) -> None:
    _write(temp_target, "Cargo.toml", "[package]\nname = 'svc'\n")
    _write(temp_target, "Cargo.lock", "version = 3\n")
    _cargo_stub(mock_bin_dir, "warning: not json")

    manifest = run_probe(temp_target, "--run-toolchains")
    assert manifest.status("cargo-licenses") != "ok"
    assert "not json" in manifest.out_content("cargo-licenses")


# Shape from real trivy 0.74.0 `fs --format json` over a Package.resolved; a malformed
# lockfile still exits 0 with SchemaVersion but no Results.
TRIVY_REPORT = (
    '{"SchemaVersion": 2, "ArtifactName": "Package.resolved", "Results": [{"Target": '
    '"Package.resolved", "Type": "swift", "Vulnerabilities": [{"VulnerabilityID": '
    '"CVE-2022-24666", "PkgName": "github.com/apple/swift-nio-http2"}]}]}'
)


def _trivy_stub(bin_dir: Path, stdout: str) -> Path:
    """A trivy stand-in that records its cwd and target argument."""
    calls = bin_dir / "trivy.calls"
    stub = bin_dir / "trivy"
    stub.write_text(
        "#!/bin/sh\n"
        f"for last; do :; done; echo \"$PWD $last\" >> '{calls}'\n"
        f"printf '%s' '{stdout}'\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return calls


def test_trivy_scans_swift_pins_from_outside_the_target(
    temp_target: Path, mock_bin_dir: Path, run_probe: RunProbe
) -> None:
    _write(temp_target, "Package.resolved", '{"pins": [], "version": 2}\n')
    _write(temp_target, "Podfile.lock", "PODS:\n  - SwiftNIOHTTP2 (1.19.0)\n")
    # a target-shipped config that, read by trivy, hides every finding
    _write(temp_target, "trivy.yaml", "severity:\n  - LOW\n")
    _write(temp_target, ".trivyignore", "CVE-2022-24666\n")
    calls = _trivy_stub(mock_bin_dir, TRIVY_REPORT)

    manifest = run_probe(temp_target, "--run-toolchains")
    assert manifest.status("swift-audit") == "ok"
    assert manifest.status("cocoapods-audit") == "ok"
    assert "CVE-2022-24666" in manifest.out_content("swift-audit")
    runs = calls.read_text(encoding="utf-8").splitlines()
    assert sorted(line.split()[1] for line in runs) == [
        str((temp_target / "Package.resolved").resolve()),
        str((temp_target / "Podfile.lock").resolve()),
    ]
    for line in runs:
        cwd = Path(line.split()[0]).resolve()
        assert cwd != temp_target.resolve(), "trivy ran where the target's trivy.yaml is read"


def test_trivy_report_without_results_is_error(
    temp_target: Path, mock_bin_dir: Path, run_probe: RunProbe
) -> None:
    _write(temp_target, "Package.resolved", "{broken\n")
    _trivy_stub(mock_bin_dir, '{"SchemaVersion": 2, "ArtifactName": "Package.resolved"}')

    manifest = run_probe(temp_target, "--run-toolchains")
    assert manifest.status("swift-audit") == "error"
    assert "printed no report" in manifest.note("swift-audit")


def test_swift_audit_refuses_without_resolved_pins(
    temp_target: Path, mock_bin_dir: Path, run_probe: RunProbe
) -> None:
    _write(temp_target, "Package.swift", "// swift-tools-version:5.9\n")
    calls = _trivy_stub(mock_bin_dir, TRIVY_REPORT)

    manifest = run_probe(temp_target, "--run-toolchains")
    assert manifest.status("swift-audit") == "n/a"
    assert "no Package.resolved" in manifest.note("swift-audit")
    assert not calls.exists()
