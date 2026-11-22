import io
import tempfile
import unittest
from pathlib import Path

from team_builder import create_app


class WebFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database = str(Path(self.temp_dir.name) / "test.sqlite3")
        self.app = create_app({"TESTING": True, "DATABASE": database, "SECRET_KEY": "test"})
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session["csrf_token"] = "token"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_import_compose_regenerate_and_save(self):
        csv_data = (
            "LINEの名前,名前,学部,回生,バレーボール経験,性別\n"
            "a,Aさん,経営学部,1,5年,男性\n"
            "b,Bさん,文学部,2,1年,女性\n"
            "c,Cさん,法学部,3,3年,男性\n"
            "d,Dさん,理工学部,1,0年,女性\n"
        ).encode("utf-8")
        response = self.client.post(
            "/members/import",
            data={"_csrf": "token", "csv_file": (io.BytesIO(csv_data), "members.csv")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 302)

        response = self.client.post(
            "/compose",
            data={
                "_csrf": "token",
                "event_name": "テスト会",
                "line_names": "a\nb\nc\nd",
                "group_mode": "team_size",
                "group_value": "2",
                "weight_experience": "5",
                "weight_department": "3",
                "weight_grade": "3",
                "weight_gender": "4",
                "weight_history": "5",
            },
        )
        self.assertEqual(response.status_code, 302)
        result_url = response.headers["Location"]
        page = self.client.get(result_url)
        self.assertEqual(page.status_code, 200)
        self.assertIn("テスト会".encode(), page.data)

        draft_id = result_url.rsplit("/", 1)[-1]
        response = self.client.post(f"/result/{draft_id}/regenerate", data={"_csrf": "token"})
        self.assertEqual(response.status_code, 302)
        response = self.client.post(f"/result/{draft_id}/save", data={"_csrf": "token"})
        self.assertEqual(response.status_code, 302)
        history = self.client.get("/history")
        self.assertIn("テスト会".encode(), history.data)


if __name__ == "__main__":
    unittest.main()
