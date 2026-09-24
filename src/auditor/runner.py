"""Auditor execution engine: orchestrates probes and produces audit evidence bundle."""

from __future__ import annotations

import os
from pathlib import Path

from auditor.bundle import BundleManager
from auditor.probes.build_inputs import run_build_input_probes
from auditor.probes.compliance import run_compliance_probes
from auditor.probes.dependencies import run_dependency_probes
from auditor.probes.git import run_git_probes
from auditor.probes.observability import run_observability_probes
from auditor.probes.runtime import run_runtime_probes
from auditor.probes.secrets import SECRET_GLOBS, run_secret_probes
from auditor.probes.size_shape import run_size_shape_probes
from auditor.probes.standards import run_standards_probes
from auditor.probes.surface import run_surface_probes
from auditor.probes.testing import run_testing_probes


class AuditRunner:
    def __init__(
        self,
        target_dir: Path,
        bundle_dir: Path | None = None,
        run_toolchains: bool = False,
        host_containers: bool = False,
        timeout: int = 120,
    ) -> None:
        self.target_dir = target_dir.resolve()
        self.bundle_dir = bundle_dir
        self.run_toolchains = run_toolchains
        self.host_containers = host_containers
        self.timeout = timeout
        checker_jobs = max(4, os.cpu_count() or 4)
        self.checker_jobs = checker_jobs

        self.bundle = BundleManager(
            target_dir=self.target_dir,
            bundle_dir=self.bundle_dir,
            timeout=self.timeout,
            run_toolchains=self.run_toolchains,
            host_containers=self.host_containers,
            checker_jobs=self.checker_jobs,
        )

    def run(self) -> Path:
        """Run all probes across the 9 axes and write bundle."""
        # 1. Provenance (git)
        git_scope = run_git_probes(
            self.bundle,
            self.target_dir,
            timeout=self.timeout,
            run_toolchains=self.run_toolchains,
        )

        # Write env.txt
        self.bundle.write_env(secret_globs=SECRET_GLOBS, git_scope=git_scope)

        # 2. Dependencies
        run_dependency_probes(
            self.bundle,
            self.target_dir,
            timeout=self.timeout,
            run_toolchains=self.run_toolchains,
        )

        # 3. Build inputs
        run_build_input_probes(self.bundle, self.target_dir)

        # 4. Runtime
        run_runtime_probes(
            self.bundle,
            self.target_dir,
            timeout=self.timeout,
            host_containers=self.host_containers,
        )

        # 5. Secrets
        run_secret_probes(self.bundle, self.target_dir)

        # 6. Surface
        run_surface_probes(self.bundle, self.target_dir)

        # 7. Declared standard
        run_standards_probes(
            self.bundle,
            self.target_dir,
            checker_jobs=self.checker_jobs,
            timeout=self.timeout,
        )

        # 8. Testing
        run_testing_probes(self.bundle, self.target_dir)

        # 9. Observability
        run_observability_probes(self.bundle, self.target_dir)

        # 10. Size & shape
        run_size_shape_probes(self.bundle, self.target_dir)

        # 11. Compliance
        run_compliance_probes(
            self.bundle,
            self.target_dir,
            timeout=self.timeout,
            run_toolchains=self.run_toolchains,
        )

        # Write summary
        self.bundle.write_summary()
        return self.bundle.bundle_dir
