"""Tests for the observed confidence level in UI data-path audit."""

import pytest
from conftest import OPENEMR_CLEAN_DIR

from auditor.ui_path.analyzer import OpenEMRScreenAnalyzer
from auditor.ui_path.models import ConfidenceLevel


def test_observed_flag_gated_by_default() -> None:
    """When --observed is not passed, traces remain static and observed_run is False."""
    if not OPENEMR_CLEAN_DIR.exists():
        pytest.skip(f"OpenEMR clean tree not found at {OPENEMR_CLEAN_DIR}")

    static_analyzer = OpenEMRScreenAnalyzer(target_root=OPENEMR_CLEAN_DIR, observed=False)
    report = static_analyzer.audit_screen("interface/patient_file/summary/demographics.php")

    assert report.observed_run is False
    assert not any(i.confidence == ConfidenceLevel.OBSERVED for i in report.items)


def test_observed_flag_elevates_confidence() -> None:
    """When --observed is enabled, verified traces elevate to observed."""
    if not OPENEMR_CLEAN_DIR.exists():
        pytest.skip(f"OpenEMR clean tree not found at {OPENEMR_CLEAN_DIR}")

    observed_analyzer = OpenEMRScreenAnalyzer(target_root=OPENEMR_CLEAN_DIR, observed=True)
    report = observed_analyzer.audit_screen("interface/patient_file/summary/demographics.php")

    assert report.observed_run is True
    observed_items = [i for i in report.items if i.confidence == ConfidenceLevel.OBSERVED]
    assert len(observed_items) > 0, "At least one item must be elevated to observed confidence"
