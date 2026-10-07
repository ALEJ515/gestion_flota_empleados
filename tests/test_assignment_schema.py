import importlib.util
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location(
    'flota_schema', Path(__file__).resolve().parents[1] / 'models' / 'flota_schema.py',
)
schema = importlib.util.module_from_spec(spec)
spec.loader.exec_module(schema)


class RecordingCursor:
    def __init__(self, table_exists=True):
        self.table_exists = table_exists
        self.statements = []

    def execute(self, sql):
        self.statements.append(' '.join(sql.split()))

    def fetchone(self):
        return ('flota_empleado' if self.table_exists else None,)


class TestAssignmentSchema(unittest.TestCase):
    def test_fresh_install_leaves_table_creation_to_odoo(self):
        cursor = RecordingCursor(table_exists=False)
        schema.prepare_employee_assignment_schema(cursor)
        self.assertEqual(cursor.statements, ["SELECT to_regclass('flota_empleado')"])

    def test_prepares_column_before_updating_legacy_records(self):
        cursor = RecordingCursor()
        schema.prepare_employee_assignment_schema(cursor)
        self.assertEqual(len(cursor.statements), 4)
        self.assertIn(
            "ADD COLUMN IF NOT EXISTS estado_asignacion VARCHAR DEFAULT 'asignada'",
            cursor.statements[1],
        )
        self.assertIn('WHERE estado_asignacion IS NULL', cursor.statements[2])
        self.assertIn('ALTER COLUMN estado_asignacion SET NOT NULL', cursor.statements[3])
        self.assertIn('ALTER COLUMN name DROP NOT NULL', cursor.statements[3])
        self.assertIn('ALTER COLUMN cargo DROP NOT NULL', cursor.statements[3])

    def test_repeated_preparation_uses_idempotent_statements(self):
        cursor = RecordingCursor()
        schema.prepare_employee_assignment_schema(cursor)
        schema.prepare_employee_assignment_schema(cursor)
        self.assertEqual(cursor.statements[:4], cursor.statements[4:])


if __name__ == '__main__':
    unittest.main()
