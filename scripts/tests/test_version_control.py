from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "check_version_control.py"
spec = importlib.util.spec_from_file_location("version_control", SOURCE)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class VersionControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="version-control-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output_temp = tempfile.TemporaryDirectory(prefix="version-source-archive-")
        self.addCleanup(self.output_temp.cleanup)
        self.output = Path(self.output_temp.name) / "source.tar.gz"
        self.env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
        self.run_git("init", "--initial-branch=main")
        self.run_git("config", "user.name", "Release Tests")
        self.run_git("config", "user.email", "tests@example.invalid")
        self.write("frontend/package.json", json.dumps({"version": "1.2.3"}))
        self.write("frontend/package-lock.json", json.dumps({"version": "1.2.3", "packages": {"": {"version": "1.2.3"}}}))
        self.write("backend/pyproject.toml", '[project]\nversion = "1.2.3"\n')
        self.write("backend/app/config.py", 'class Settings:\n    app_version: str = "1.2.3"\n')
        self.write("CHANGELOG.md", "# Changelog\n\n## [Unreleased]\n\n## [1.2.3] - 2026-10-10\n\n- Release notes.\n")
        self.write("README.md", "Source archive fixture.\n")
        self.write("docker-compose.yml", "services: {}\n")
        self.write("docker-compose.dev.yml", "services: {}\n")
        self.write(".gitignore", "exports/\nlocal-reviews/\nuploads/\n.env\n")
        self.write("scripts/check_version_control.py", SOURCE.read_text())
        self.write("scripts/build_release_package.sh", SOURCE.with_name("build_release_package.sh").read_text())
        self.write("deploy-to-windows.sh", (SOURCE.parents[1] / "deploy-to-windows.sh").read_text())
        self.commit()

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def run_git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.root), *args], env=self.env, stderr=subprocess.PIPE).decode()

    def commit(self):
        self.run_git("add", ".")
        self.run_git("commit", "-m", "test fixture")

    def tag(self):
        self.run_git("tag", "-a", "v1.2.3", "-m", "release fixture")

    def assert_error(self, result, text):
        self.assertFalse(result["ok"])
        self.assertTrue(any(text in error for error in result["errors"]), result)

    def test_development_allows_uncommitted_code_but_does_not_hide_it(self):
        self.write("new-source.py", "pass\n")
        result = checker.check(self.root)
        self.assertTrue(result["ok"])
        self.assertTrue(result["dirty"])
        self.assertEqual(self.run_git("status", "--porcelain").strip(), "?? new-source.py")

    def test_clean_annotated_release_passes_without_mutation(self):
        self.tag()
        before = self.run_git("show-ref")
        self.assertTrue(checker.check(self.root, release=True, tag="v1.2.3")["ok"])
        self.assertEqual(before, self.run_git("show-ref"))
        self.assertEqual("", self.run_git("status", "--porcelain"))

    def test_each_version_location_is_checked(self):
        for name, content in [
            ("frontend/package-lock.json", '{"version":"1.2.4","packages":{"":{"version":"1.2.3"}}}'),
            ("frontend/package-lock.json", '{"version":"1.2.3","packages":{"":{"version":"1.2.4"}}}'),
            ("backend/pyproject.toml", '[project]\nversion="1.2.4"'),
            ("backend/app/config.py", 'class Settings:\n app_version: str = "1.2.4"'),
        ]:
            with self.subTest(name=name, content=content):
                original = (self.root / name).read_text()
                self.write(name, content)
                self.assert_error(checker.check(self.root), "does not match")
                self.write(name, original)

    def test_invalid_or_missing_metadata_fails_without_echoing_contents(self):
        self.write("frontend/package.json", "not valid JSON secret-value")
        result = checker.check(self.root)
        self.assert_error(result, "Unable to inspect")
        self.assertNotIn("secret-value", json.dumps(result))

    def test_non_semantic_version_is_rejected(self):
        for value in ["01.2.3", "v1.2.3", "1.2", "1.2.3-dev", None]:
            with self.subTest(value=value):
                self.write("frontend/package.json", json.dumps({"version": value}))
                self.assert_error(checker.check(self.root), "stable X.Y.Z")

    def test_missing_or_duplicate_unreleased_section_is_rejected(self):
        self.write("CHANGELOG.md", "## [1.2.3] - 2026-10-10\n- Notes\n")
        self.assert_error(checker.check(self.root), "exactly one [Unreleased]")
        self.write("CHANGELOG.md", "## [Unreleased]\n\n## [Unreleased]\n")
        self.assert_error(checker.check(self.root), "exactly one [Unreleased]")

    def test_release_rejects_untracked_staged_and_modified_files(self):
        self.tag()
        self.write("new.py", "pass\n")
        self.assert_error(checker.check(self.root, release=True), "clean working tree")
        self.run_git("add", "new.py")
        self.assert_error(checker.check(self.root, release=True), "clean working tree")
        self.commit()
        self.write("new.py", "x = 1\n")
        self.assert_error(checker.check(self.root, release=True), "clean working tree")

    def test_lightweight_missing_old_target_and_wrong_requested_tag_fail(self):
        self.assert_error(checker.check(self.root, release=True), "tag is missing")
        self.run_git("tag", "v1.2.3")
        self.assert_error(checker.check(self.root, release=True), "annotated version tag")
        self.run_git("tag", "-d", "v1.2.3")
        self.tag()
        self.write("new.py", "pass\n")
        self.commit()
        self.assert_error(checker.check(self.root, release=True), "point at HEAD")
        self.assert_error(checker.check(self.root, release=True, tag="v1.2.4"), "Requested tag")

    def test_release_requires_dated_nonempty_version_notes(self):
        self.tag()
        for notes in [
            "## [Unreleased]\n", "## [Unreleased]\n\n## [1.2.3] - Unreleased\n- Notes\n",
            "## [Unreleased]\n\n## [1.2.3] - 2026-10-10\n\n### Fixed\n",
            "## [Unreleased]\n\n## [1.2.3] - 2026-99-99\n- Notes\n",
        ]:
            with self.subTest(notes=notes):
                self.write("CHANGELOG.md", notes)
                self.assertFalse(checker.check(self.root, release=True)["ok"])

    def test_private_and_runtime_paths_are_rejected_even_force_added(self):
        for name in ["exports/a.json", "local-reviews/image.png", ".release/current.json",
                     "backend/private_publish_snapshots/a.png", "backend/.env.production", "backend/local.db"]:
            with self.subTest(name=name):
                self.assertTrue(checker.forbidden_path(name))
        self.write(".gitignore", "/exports/\n")
        self.write("exports/a.json", "{}")
        self.run_git("add", "-f", "exports/a.json")
        self.assert_error(checker.check(self.root), "Runtime/private files")

    def test_templates_and_existing_test_fixture_are_allowed(self):
        for name in ["backend/.env.example", "backend/.env.test.example", "backend/.env.test",
                     "frontend/package-lock.json", "docs/release.md", "backend/tests/test_snapshots.py"]:
            with self.subTest(name=name):
                self.assertFalse(checker.forbidden_path(name))
        self.assertTrue(checker.forbidden_path("frontend/.env.test"))

    def test_cli_release_failure_returns_nonzero_and_readable_json(self):
        result = subprocess.run([sys.executable, str(SOURCE), "--repo", str(self.root), "--release"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(json.loads(result.stdout)["ok"])

    def package(self, output=None):
        return subprocess.run(
            ["bash", str(self.root / "scripts/build_release_package.sh"), "1.2.3", str(output or self.output)],
            env={**self.env, "PYTHON_BIN": sys.executable}, capture_output=True, text=True,
        )

    def test_source_archive_contains_only_committed_source_and_no_mcp_claim(self):
        self.tag()
        self.write("exports/private.json", "private review data")
        self.write("backend/.env", "private runtime data")
        self.write("uploads/image.png", "image")
        result = self.package()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("not a production package", result.stderr)
        with tarfile.open(self.output) as archive:
            names = archive.getnames()
            self.assertIn("backend/app/config.py", names)
            self.assertIn("CHANGELOG.md", names)
            self.assertFalse(any(".env" in name or name.startswith(("uploads/", "exports/")) for name in names))
            self.assertEqual(archive.extractfile("README.md").read(), b"Source archive fixture.\n")
        self.assertEqual("", self.run_git("status", "--porcelain"))

    def test_source_archive_rejects_dirty_tree_before_creating_output(self):
        self.tag()
        self.write("backend/new.py", "pass\n")
        self.assertNotEqual(self.package().returncode, 0)
        self.assertFalse(self.output.exists())

    def test_deploy_rejects_dirty_candidate_before_mcp_or_remote_access(self):
        self.tag()
        self.write("backend/new.py", "pass\n")
        result = subprocess.run(
            ["bash", str(self.root / "deploy-to-windows.sh")],
            env={**self.env, "PYTHON_BIN": sys.executable, "PROJECT": str(self.root),
                 "MCP_PROJECT": str(self.root / "missing-mcp-sentinel")},
            capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assert_error(json.loads(result.stdout), "clean working tree")
        self.assertNotIn("missing-mcp-sentinel", result.stderr)

    def test_source_archive_rejects_repository_output_and_preserves_existing_archive(self):
        self.tag()
        self.assertNotEqual(self.package(self.root / "source.tar.gz").returncode, 0)
        self.assertFalse((self.root / "source.tar.gz").exists())
        self.output.write_bytes(b"original archive")
        self.assertNotEqual(self.package().returncode, 0)
        self.assertEqual(self.output.read_bytes(), b"original archive")


if __name__ == "__main__":
    unittest.main()
