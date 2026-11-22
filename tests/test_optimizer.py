import unittest

from team_builder.optimizer import build_teams, score_teams


def member(member_id, name, experience, department, grade, gender):
    return {
        "id": member_id,
        "line_name": name,
        "experience": experience,
        "department": department,
        "grade": grade,
        "gender": gender,
    }


class OptimizerTests(unittest.TestCase):
    def setUp(self):
        self.members = [
            member(1, "a", 10, "A", 1, "男性"),
            member(2, "b", 8, "A", 2, "女性"),
            member(3, "c", 1, "B", 1, "男性"),
            member(4, "d", 0, "B", 2, "女性"),
        ]

    def test_balances_team_sizes_and_experience(self):
        teams = build_teams(self.members, mode="team_size", value=2, seed=7)
        self.assertEqual([len(team) for team in teams], [2, 2])
        averages = [sum(item["experience"] for item in team) / 2 for team in teams]
        self.assertLessEqual(abs(averages[0] - averages[1]), 1.5)

    def test_history_weight_avoids_old_pair(self):
        weights = {"experience": 0, "department": 0, "grade": 0, "gender": 0, "history": 5}
        teams = build_teams(
            self.members,
            mode="team_size",
            value=2,
            weights=weights,
            pair_counts={(1, 2): 10},
            seed=11,
        )
        pairs = [{item["id"] for item in team} for team in teams]
        self.assertNotIn({1, 2}, pairs)
        self.assertEqual(score_teams(teams, weights, {(1, 2): 10}), 0)


if __name__ == "__main__":
    unittest.main()
