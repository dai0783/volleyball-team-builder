import sqlite3
import unittest

from team_builder.csv_import import import_members, normalize_key
from team_builder.db import SCHEMA


class CsvImportTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)

    def tearDown(self):
        self.connection.close()

    def test_imports_google_sheet_style_headers(self):
        raw = (
            "LINE の名前,名前（フルネーム・漢字）例:山本太郎,学部（漢字）,回生（半角数字）,"
            "バレーボール経験(年数),性別\n"
            "たろう,山本太郎,経営学部,2,3年,男性\n"
        ).encode("utf-8")
        result = import_members(self.connection, raw)
        member = self.connection.execute("SELECT * FROM members").fetchone()
        self.assertEqual(result.imported, 1)
        self.assertEqual(member["line_name"], "たろう")
        self.assertEqual(member["full_name"], "山本太郎")
        self.assertEqual(member["grade"], 2)
        self.assertEqual(member["experience"], 3)

    def test_normalization_ignores_width_spaces_and_case(self):
        self.assertEqual(normalize_key(" Ｔaro  "), normalize_key("taro"))


if __name__ == "__main__":
    unittest.main()
