import os
import tempfile
import unittest

import database


class DatabaseInitializationTests(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        handle.close()
        self.db_path = handle.name
        self.original_db_file = database.DB_FILE
        database.DB_FILE = self.db_path

    def tearDown(self):
        database.DB_FILE = self.original_db_file
        os.unlink(self.db_path)

    def test_reinitialization_preserves_existing_data(self):
        database.init_db()
        conn = database.get_db_connection()
        try:
            conn.execute(
                """
                INSERT INTO patients
                    (id, name, age, height_cm, weight_kg, healthy_leg, prosthetic_leg)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                ("p-test", "Test Patient", 30, 170, 60, "LEFT", "RIGHT"),
            )
            conn.commit()
        finally:
            conn.close()

        database.init_db()

        conn = database.get_db_connection()
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM patients WHERE id = ?", ("p-test",)
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(count, 1)

    def test_connections_enable_foreign_keys_and_schema_version(self):
        database.init_db()
        conn = database.get_db_connection()
        try:
            foreign_keys = conn.execute("PRAGMA foreign_keys").fetchone()[0]
            schema_version = conn.execute("PRAGMA user_version").fetchone()[0]
        finally:
            conn.close()

        self.assertEqual(foreign_keys, 1)
        self.assertEqual(schema_version, 1)


if __name__ == "__main__":
    unittest.main()
