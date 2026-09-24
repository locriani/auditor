"""Tests for secret-scan, env-files, and published-ports probes."""

from __future__ import annotations

from pathlib import Path

from conftest import RunProbe


def test_secret_scan_length_threshold(temp_target: Path, run_probe: RunProbe) -> None:
    # 6-character literal should match
    f6 = temp_target / "config_6.py"
    f6.write_text('api_key = "123456"\n', encoding="utf-8")

    manifest = run_probe(temp_target)
    out = manifest.out_content("secret-scan")
    assert "123456" in out

    # 5-character literal should not match
    f6.unlink()
    f5 = temp_target / "config_5.py"
    f5.write_text('api_key = "12345"\n', encoding="utf-8")

    manifest = run_probe(temp_target)
    assert manifest.status("secret-scan") == "empty"


def test_secret_scan_shapes(temp_target: Path, run_probe: RunProbe) -> None:
    test_file = temp_target / "app.js"
    test_file.write_text(
        """
        const db_password = "supersecretpassword";
        const secretKey = "another_secret_1234";
        const url_creds = "postgres://user:dbpass123@localhost:5432/db";
        // Plural should be ignored
        const tokens = ["item1", "item2"];
        // Call should be ignored
        const tokenExpiry = Date.now();
        const passwd = generatePassword();
        // Placeholder should be ignored
        const password = "changeme123";
        const example_key = "example_value_1234";
        """,
        encoding="utf-8",
    )

    manifest = run_probe(temp_target)
    out = manifest.out_content("secret-scan")

    assert "supersecretpassword" in out
    assert "another_secret_1234" in out
    assert "dbpass123@" in out

    assert "changeme123" not in out
    assert "example_value_1234" not in out
    assert "generatePassword" not in out
    assert "Date.now" not in out


def test_secret_scan_empty_note(temp_target: Path, run_probe: RunProbe) -> None:
    manifest = run_probe(temp_target)
    assert manifest.status("secret-scan") == "empty"
    assert "finds one-line assignments and URL credentials only" in manifest.note("secret-scan")


def test_env_files_probe(temp_target: Path, run_probe: RunProbe) -> None:
    (temp_target / ".env").write_text("A=1\n", encoding="utf-8")
    (temp_target / ".env.production").write_text("B=2\n", encoding="utf-8")

    manifest = run_probe(temp_target)
    assert manifest.status("env-files") == "ok"
    out = manifest.out_content("env-files")
    assert "./.env" in out
    assert "./.env.production" in out


def test_published_ports_probe(temp_target: Path, run_probe: RunProbe) -> None:
    compose = temp_target / "docker-compose.yml"
    compose.write_text(
        """
        services:
          web:
            ports:
              - "8080:80"
              - 3000:3000
        """,
        encoding="utf-8",
    )

    manifest = run_probe(temp_target)
    assert manifest.status("published-ports") == "ok"
    out = manifest.out_content("published-ports")
    assert "8080:80" in out
    assert "3000:3000" in out
