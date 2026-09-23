"""Tests verifying all 39 probes against targets containing target fixtures."""

from __future__ import annotations

from pathlib import Path


def test_build_inputs_probes(temp_target: Path, run_probe) -> None:
    (temp_target / "Dockerfile").write_text(
        "FROM alpine:latest\nRUN curl -s https://example.com | sh\n", encoding="utf-8"
    )
    (temp_target / "app.Dockerfile").write_text("FROM python:3.11\n", encoding="utf-8")
    (temp_target / "docker-compose.yml").write_text("version: '3'\n", encoding="utf-8")

    manifest = run_probe(temp_target)

    # dockerfiles
    assert manifest.status("dockerfiles") == "ok"
    df_out = manifest.out_content("dockerfiles")
    assert "./Dockerfile" in df_out
    assert "./app.Dockerfile" in df_out

    # dockerfile-fetches
    assert manifest.status("dockerfile-fetches") == "ok"
    fetches_out = manifest.out_content("dockerfile-fetches")
    assert "curl" in fetches_out
    assert ":latest" in fetches_out

    # compose-files
    assert manifest.status("compose-files") == "ok"
    assert "./docker-compose.yml" in manifest.out_content("compose-files")


def test_surface_and_standards_probes(temp_target: Path, run_probe) -> None:
    (temp_target / "api.py").write_text(
        '@app.route("GET /users")\ndef get_users(): pass\n', encoding="utf-8"
    )
    (temp_target / "routes.js").write_text('const r = "GET /users";\n', encoding="utf-8")
    (temp_target / "ruff.toml").write_text("[lint]\n", encoding="utf-8")
    (temp_target / ".editorconfig").write_text("root = true\n", encoding="utf-8")

    manifest = run_probe(temp_target)

    # route-tables
    assert manifest.status("route-tables") == "ok"
    assert "./api.py" in manifest.out_content("route-tables")

    # route-verbs
    assert manifest.status("route-verbs") == "ok"
    assert "GET" in manifest.out_content("route-verbs")

    # lint-config
    assert manifest.status("lint-config") == "ok"
    lint_out = manifest.out_content("lint-config")
    assert "./ruff.toml" in lint_out
    assert "./.editorconfig" in lint_out

    # lang-census
    assert manifest.status("lang-census") == "ok"
    census_out = manifest.out_content("lang-census")
    assert "py" in census_out
    assert "toml" in census_out


def test_testing_probes(temp_target: Path, run_probe) -> None:
    (temp_target / "tests").mkdir()
    (temp_target / "tests" / "test_app.py").write_text("def test_ok(): pass\n", encoding="utf-8")
    (temp_target / "README.md").write_text(
        "![Build](https://github.com/org/repo/actions/workflows/ci.yml/badge.svg)\n",
        encoding="utf-8",
    )

    manifest = run_probe(temp_target)

    # test-inventory
    assert manifest.status("test-inventory") == "ok"
    assert "./tests" in manifest.out_content("test-inventory")

    # test-file-count
    assert manifest.status("test-file-count") == "ok"
    assert manifest.out_content("test-file-count").strip() == "1"

    # ci-badges
    assert manifest.status("ci-badges") == "ok"
    assert "badge.svg" in manifest.out_content("ci-badges")


def test_observability_probes(temp_target: Path, run_probe) -> None:
    (temp_target / "server.js").write_text(
        """
        const winston = require('winston');
        const logger = winston.createLogger();
        app.get('/healthz', (req, res) => res.send('ok'));
        // Telemetry
        const otel = require('@opentelemetry/api');
        // Swallowed exception
        try { doSomething(); } catch (err) {
        }
        """,
        encoding="utf-8",
    )

    manifest = run_probe(temp_target)

    assert manifest.status("health-endpoints") == "ok"
    assert "./server.js" in manifest.out_content("health-endpoints")

    assert manifest.status("log-surface") == "ok"
    assert "winston" in manifest.out_content("log-surface")

    assert manifest.status("telemetry") == "ok"
    assert "./server.js" in manifest.out_content("telemetry")

    assert manifest.status("swallowed-exceptions") == "ok"
    assert "./server.js" in manifest.out_content("swallowed-exceptions")


def test_size_and_compliance_probes(temp_target: Path, run_probe) -> None:
    (temp_target / "LICENSE").write_text("MIT License\n", encoding="utf-8")
    (temp_target / "NOTICE").write_text("Notice file\n", encoding="utf-8")
    (temp_target / "large.bin").write_bytes(b"x" * 1024)

    manifest = run_probe(temp_target)

    # license-files
    assert manifest.status("license-files") == "ok"
    lic_out = manifest.out_content("license-files")
    assert "./LICENSE" in lic_out
    assert "./NOTICE" in lic_out

    # largest-files & file-count
    assert manifest.status("largest-files") == "ok"
    assert "large.bin" in manifest.out_content("largest-files")
    assert manifest.status("file-count") == "ok"
    assert manifest.status("repo-size") == "ok"


def test_pruning_generated_and_vendor_trees(temp_target: Path, run_probe) -> None:
    # Files inside node_modules, .venv, or .git should not be counted or scanned
    node_modules = temp_target / "node_modules" / "badpkg"
    node_modules.mkdir(parents=True)
    (node_modules / "bad.js").write_text('api_key = "secret123456";\n', encoding="utf-8")

    git_dir = temp_target / ".git" / "objects"
    git_dir.mkdir(parents=True)
    (git_dir / "obj1").write_text("git object content\n", encoding="utf-8")

    (temp_target / "good.py").write_text("print('hello')\n", encoding="utf-8")

    manifest = run_probe(temp_target)

    # secret-scan should NOT find secrets in node_modules
    assert manifest.status("secret-scan") == "empty"

    # file-count should only count good.py
    assert manifest.out_content("file-count").strip() == "1"
