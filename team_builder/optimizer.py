from __future__ import annotations

import math
import random
import statistics
from collections import Counter
from itertools import combinations


DEFAULT_WEIGHTS = {
    "experience": 5,
    "department": 3,
    "grade": 3,
    "gender": 4,
    "history": 5,
}


def _gender_group(value: object) -> str:
    text = str(value or "").strip().lower()
    if text in {"男", "男性", "male", "m"}:
        return "male"
    if text in {"女", "女性", "female", "f"}:
        return "female"
    return "unknown"


def _team_sizes(member_count: int, mode: str, value: int) -> list[int]:
    if member_count < 1:
        return []
    if mode == "team_count":
        team_count = max(1, min(value, member_count))
    else:
        team_count = max(1, math.ceil(member_count / max(1, value)))
    base, remainder = divmod(member_count, team_count)
    return [base + (1 if index < remainder else 0) for index in range(team_count)]


def _same_value_penalty(team: list[dict], field: str) -> float:
    if len(team) < 2:
        return 0.0
    values = [str(member.get(field) or "").strip() for member in team]
    known = [value for value in values if value]
    if len(known) < 2:
        return 0.0
    counts = Counter(known)
    same_pairs = sum(count * (count - 1) / 2 for count in counts.values())
    all_pairs = len(known) * (len(known) - 1) / 2
    return same_pairs / all_pairs


def score_teams(
    teams: list[list[dict]],
    weights: dict[str, int],
    pair_counts: dict[tuple[int, int], int],
) -> float:
    members = [member for team in teams for member in team]
    if not members:
        return 0.0

    experiences = [float(member.get("experience") or 0) for member in members]
    global_average = statistics.fmean(experiences)
    scale = max(1.0, statistics.pstdev(experiences) if len(experiences) > 1 else 1.0)
    experience_penalty = statistics.fmean(
        ((statistics.fmean(float(member.get("experience") or 0) for member in team) - global_average) / scale) ** 2
        for team in teams
        if team
    )

    department_penalty = statistics.fmean(_same_value_penalty(team, "department") for team in teams)
    grade_penalty = statistics.fmean(_same_value_penalty(team, "grade") for team in teams)

    gender_penalties = []
    male_counts = []
    female_counts = []
    for team in teams:
        genders = Counter(_gender_group(member.get("gender")) for member in team)
        male = genders["male"]
        female = genders["female"]
        known = male + female
        gender_penalties.append(abs(male - female) / known if known else 0.0)
        male_counts.append(male)
        female_counts.append(female)
    balance_penalty = statistics.fmean(gender_penalties) if gender_penalties else 0.0
    distribution_penalty = 0.0
    for counts in (male_counts, female_counts):
        total = sum(counts)
        if total:
            target = total / len(teams)
            distribution_penalty += sum(abs(count - target) for count in counts) / total
    gender_penalty = balance_penalty + distribution_penalty / 2

    history_total = 0
    pair_total = 0
    for team in teams:
        for first, second in combinations(team, 2):
            pair = tuple(sorted((int(first["id"]), int(second["id"]))))
            history_total += pair_counts.get(pair, 0)
            pair_total += 1
    history_penalty = history_total / max(1, pair_total)

    return (
        weights.get("experience", 0) * experience_penalty
        + weights.get("department", 0) * department_penalty
        + weights.get("grade", 0) * grade_penalty
        + weights.get("gender", 0) * gender_penalty
        + weights.get("history", 0) * history_penalty
    )


def _random_assignment(members: list[dict], sizes: list[int], rng: random.Random) -> list[list[dict]]:
    shuffled = members[:]
    rng.shuffle(shuffled)
    teams = []
    offset = 0
    for size in sizes:
        teams.append(shuffled[offset : offset + size])
        offset += size
    return teams


def build_teams(
    members: list[dict],
    *,
    mode: str = "team_size",
    value: int = 6,
    weights: dict[str, int] | None = None,
    pair_counts: dict[tuple[int, int], int] | None = None,
    seed: int | None = None,
) -> list[list[dict]]:
    if not members:
        raise ValueError("参加者がいません。")

    weights = {**DEFAULT_WEIGHTS, **(weights or {})}
    pair_counts = pair_counts or {}
    rng = random.Random(seed)
    sizes = _team_sizes(len(members), mode, value)

    best_teams = _random_assignment(members, sizes, rng)
    best_score = score_teams(best_teams, weights, pair_counts)
    restarts = min(18, max(6, len(members) // 2))
    iterations = min(5000, max(900, len(members) * 90))

    for _restart in range(restarts):
        current = _random_assignment(members, sizes, rng)
        current_score = score_teams(current, weights, pair_counts)
        for iteration in range(iterations // restarts):
            if len(current) < 2:
                break
            first_team, second_team = rng.sample(range(len(current)), 2)
            if not current[first_team] or not current[second_team]:
                continue
            first_index = rng.randrange(len(current[first_team]))
            second_index = rng.randrange(len(current[second_team]))
            current[first_team][first_index], current[second_team][second_index] = (
                current[second_team][second_index],
                current[first_team][first_index],
            )
            candidate_score = score_teams(current, weights, pair_counts)
            temperature = max(0.01, 1 - iteration / max(1, iterations // restarts))
            delta = candidate_score - current_score
            accept = delta <= 0 or rng.random() < math.exp(-delta / temperature)
            if accept:
                current_score = candidate_score
                if candidate_score < best_score:
                    best_score = candidate_score
                    best_teams = [team[:] for team in current]
            else:
                current[first_team][first_index], current[second_team][second_index] = (
                    current[second_team][second_index],
                    current[first_team][first_index],
                )

    for team in best_teams:
        team.sort(key=lambda member: (-float(member.get("experience") or 0), member["line_name"]))
    return best_teams


def team_summary(team: list[dict]) -> dict:
    experiences = [float(member.get("experience") or 0) for member in team]
    genders = Counter(_gender_group(member.get("gender")) for member in team)
    return {
        "average_experience": round(statistics.fmean(experiences), 1) if experiences else 0,
        "male": genders["male"],
        "female": genders["female"],
        "unknown": genders["unknown"],
        "departments": len({member.get("department") for member in team if member.get("department")}),
        "grades": len({member.get("grade") for member in team if member.get("grade")}),
    }


def format_teams(teams: list[list[dict]], event_name: str = "") -> str:
    lines: list[str] = []
    if event_name.strip():
        lines.extend([event_name.strip(), ""])
    for index, team in enumerate(teams, start=1):
        lines.append(f"【チーム{index}】")
        lines.extend(member["line_name"] for member in team)
        if index != len(teams):
            lines.append("")
    return "\n".join(lines)
