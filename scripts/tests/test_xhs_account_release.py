import ast
import hashlib
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class XhsAccountReleaseTests(unittest.TestCase):
    def test_preservation_is_an_explicit_distinct_policy(self):
        script = (ROOT / 'scripts/windows/Deploy-Release.ps1').read_text()
        self.assertIn('[switch]$PreserveXhsAccountSchema', script)
        self.assertIn('$PreserveAdditiveSchema -and $PreserveXhsAccountSchema', script)
        self.assertIn('-not $PreserveAdditiveSchema -and -not $PreserveXhsAccountSchema', script)
        self.assertIn('$servicesStopped -and $rollbackDataSafe', script)
        self.assertLess(script.index('Assert-XhsAccountMigrationRevision $preMigrationRevision'), script.index('stop frontend'))
        self.assertLess(script.index('Assert-XhsAccountMigrationRevision $postMigrationRevision'), script.index('up -d --no-deps backend'))
        self.assertLess(script.index('Application rollback withheld'), script.index('if ($servicesStopped -and $rollbackDataSafe)'))

    def test_audited_migrations_are_pinned_and_nondestructive(self):
        policy = (ROOT / 'scripts/windows/Xhs-AccountMigration.ps1').read_text()
        for name in ('e61112a0b001_xhs_cloud_import.py', 'e61113a0b001_xhs_account_master.py', 'e61113b0b002_xhs_master_cutover.py'):
            source = (ROOT / 'backend/app/alembic/versions' / name).read_bytes()
            self.assertIn(hashlib.sha256(source).hexdigest(), policy)
            upgrade = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == 'upgrade')
            calls = [n.func.attr for n in ast.walk(upgrade) if isinstance(n, ast.Call)
                     and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name)
                     and n.func.value.id in ('op', 'batch')]
            self.assertTrue(calls)
            self.assertTrue(set(calls) <= {'add_column', 'create_table', 'create_index', 'batch_alter_table',
                                         'alter_column', 'create_foreign_key', 'create_unique_constraint'})

    def test_entrypoint_requires_explicit_flag(self):
        source = (ROOT / 'deploy-to-windows.sh').read_text()
        self.assertIn('PRESERVE_XHS_ACCOUNT_SCHEMA="${PRESERVE_XHS_ACCOUNT_SCHEMA:-false}"', source)
        self.assertIn('BACKUP_ARG+=" -PreserveXhsAccountSchema"', source)
        self.assertIn('"$PRESERVE_ADDITIVE_SCHEMA" == "false"', source)


if __name__ == '__main__':
    unittest.main()
