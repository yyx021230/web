from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class AdditiveReleaseRollbackTests(unittest.TestCase):
    def test_database_restore_is_opt_out_only_for_explicit_additive_mode(self):
        source = (ROOT / "scripts/windows/Deploy-Release.ps1").read_text()
        self.assertIn("[switch]$PreserveAdditiveSchema", source)
        self.assertIn("$backupDir -and $migrationAttempted -and -not $PreserveAdditiveSchema", source)
        self.assertIn("$preMigrationRevision -ne 'c47f2a6d9b10'", source)
        self.assertIn("$postMigrationRevision -ne 'e61010a0b001'", source)
        self.assertLess(source.index("$preMigrationRevision -ne 'c47f2a6d9b10'"), source.index("stop frontend"))
        self.assertLess(source.index("$postMigrationRevision -ne 'e61010a0b001'"), source.index("up -d --no-deps backend"))

    def test_entrypoint_requires_explicit_flag_and_protects_ssh_credentials(self):
        source = (ROOT / "deploy-to-windows.sh").read_text()
        self.assertIn('PRESERVE_ADDITIVE_SCHEMA="${PRESERVE_ADDITIVE_SCHEMA:-false}"', source)
        self.assertIn('BACKUP_ARG+=" -PreserveAdditiveSchema"', source)
        self.assertNotIn('sshpass -p', source)
        self.assertIn('export SSHPASS="$WIN_PASS"', source)
        self.assertIn('StrictHostKeyChecking=yes', source)

    def test_audited_chain_only_creates_tables_and_indexes(self):
        import ast

        for name in ("d5a8c2e7f901_cloud_phone_publish_jobs.py", "e61010a0b001_browser_sessions.py"):
            tree = ast.parse((ROOT / "backend/app/alembic/versions" / name).read_text())
            upgrade = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "upgrade")
            operations = [node for node in ast.walk(upgrade) if isinstance(node, ast.Call)
                          and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                          and node.func.value.id == "op"]
            self.assertTrue(operations)
            self.assertTrue(all(node.func.attr in {"create_table", "create_index"} for node in operations))


if __name__ == "__main__":
    unittest.main()
