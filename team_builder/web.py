from __future__ import annotations

import csv
import difflib
import io
import json
import secrets
from datetime import datetime, timedelta, timezone
from itertools import combinations

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

from .csv_import import import_members, normalize_key, normalize_text
from .db import get_db
from .optimizer import DEFAULT_WEIGHTS, build_teams, format_teams, team_summary


bp = Blueprint("web", __name__)
_api_keys: dict[str, str] = {}


def _now_jst() -> str:
    return datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M:%S")


def _csrf_token() -> str:
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(24)
    return session["csrf_token"]


@bp.app_context_processor
def inject_helpers() -> dict:
    return {"csrf_token": _csrf_token}


@bp.before_app_request
def protect_post_requests():
    if request.method == "POST":
        expected = session.get("csrf_token", "")
        supplied = request.form.get("_csrf", "")
        if not expected or not secrets.compare_digest(expected, supplied):
            abort(400, "送信内容を確認できませんでした。画面を再読み込みしてください。")


def _member_dict(row) -> dict:
    return dict(row)


def _index_context(form_state: dict | None = None, errors: list[str] | None = None) -> dict:
    connection = get_db()
    member_count = connection.execute("SELECT COUNT(*) FROM members").fetchone()[0]
    history_count = connection.execute("SELECT COUNT(*) FROM formations").fetchone()[0]
    state = {
        "event_name": "",
        "line_names": "",
        "group_mode": "team_size",
        "group_value": 6,
        **{f"weight_{key}": value for key, value in DEFAULT_WEIGHTS.items()},
    }
    if form_state:
        state.update(form_state)
    return {
        "member_count": member_count,
        "history_count": history_count,
        "state": state,
        "errors": errors or [],
    }


@bp.get("/")
def index():
    return render_template("index.html", **_index_context())


def _parse_weights() -> dict[str, int]:
    weights = {}
    for key in DEFAULT_WEIGHTS:
        try:
            weights[key] = max(0, min(5, int(request.form.get(f"weight_{key}", DEFAULT_WEIGHTS[key]))))
        except ValueError:
            weights[key] = DEFAULT_WEIGHTS[key]
    return weights


def _history_pairs(connection) -> dict[tuple[int, int], int]:
    rows = connection.execute(
        """
        SELECT member_a, member_b, COUNT(*) AS frequency
        FROM formation_pairs
        GROUP BY member_a, member_b
        """
    ).fetchall()
    return {(row["member_a"], row["member_b"]): row["frequency"] for row in rows}


def _members_from_ids(connection, member_ids: list[int]) -> list[dict]:
    if not member_ids:
        return []
    placeholders = ",".join("?" for _ in member_ids)
    rows = connection.execute(
        f"SELECT * FROM members WHERE id IN ({placeholders})", member_ids
    ).fetchall()
    by_id = {row["id"]: _member_dict(row) for row in rows}
    return [by_id[member_id] for member_id in member_ids if member_id in by_id]


@bp.post("/compose")
def compose():
    connection = get_db()
    form_state = request.form.to_dict()
    event_name = normalize_text(request.form.get("event_name"))
    raw_names = request.form.get("line_names", "")
    names = [normalize_text(line) for line in raw_names.splitlines() if normalize_text(line)]
    errors: list[str] = []

    if len(names) < 2:
        errors.append("LINEの名前を2人以上入力してください。")

    input_keys: set[str] = set()
    duplicates: list[str] = []
    members: list[dict] = []
    all_rows = connection.execute("SELECT * FROM members ORDER BY line_name").fetchall()
    all_members = [_member_dict(row) for row in all_rows]
    by_key = {member["line_key"]: member for member in all_members}

    for name in names:
        key = normalize_key(name)
        if key in input_keys:
            duplicates.append(name)
            continue
        input_keys.add(key)
        member = by_key.get(key)
        if member:
            members.append(member)
            continue

        close_keys = difflib.get_close_matches(key, list(by_key), n=2, cutoff=0.65)
        suggestions = "、".join(by_key[item]["line_name"] for item in close_keys)
        message = f"会員リストに『{name}』が見つかりません。"
        if suggestions:
            message += f" 近い名前：{suggestions}"
        errors.append(message)

    if duplicates:
        errors.append("同じLINEの名前が複数回入力されています：" + "、".join(duplicates))

    mode = request.form.get("group_mode", "team_size")
    if mode not in {"team_size", "team_count"}:
        mode = "team_size"
    try:
        group_value = int(request.form.get("group_value", "6"))
    except ValueError:
        group_value = 0
    if group_value < 1:
        errors.append("チーム人数またはチーム数は1以上にしてください。")

    if errors:
        return render_template("index.html", **_index_context(form_state, errors)), 400

    weights = _parse_weights()
    settings = {
        "mode": mode,
        "value": group_value,
        "weights": weights,
        "seed": secrets.randbits(63),
    }
    teams = build_teams(
        members,
        mode=mode,
        value=group_value,
        weights=weights,
        pair_counts=_history_pairs(connection),
        seed=settings["seed"],
    )
    draft_id = secrets.token_urlsafe(18)
    team_ids = [[member["id"] for member in team] for team in teams]
    output_text = format_teams(teams, event_name)
    connection.execute(
        """
        INSERT INTO drafts (id, event_name, member_ids_json, settings_json, teams_json, output_text)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            draft_id,
            event_name,
            json.dumps([member["id"] for member in members]),
            json.dumps(settings, ensure_ascii=False),
            json.dumps(team_ids),
            output_text,
        ),
    )
    connection.commit()
    session["draft_id"] = draft_id
    return redirect(url_for("web.result", draft_id=draft_id))


def _load_owned_draft(connection, draft_id: str):
    if session.get("draft_id") != draft_id:
        abort(404)
    draft = connection.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
    if draft is None:
        abort(404)
    return draft


def _inflate_teams(connection, team_ids: list[list[int]]) -> list[list[dict]]:
    flat_ids = [member_id for team in team_ids for member_id in team]
    members = _members_from_ids(connection, flat_ids)
    by_id = {member["id"]: member for member in members}
    return [[by_id[member_id] for member_id in team if member_id in by_id] for team in team_ids]


@bp.get("/result/<draft_id>")
def result(draft_id: str):
    connection = get_db()
    draft = _load_owned_draft(connection, draft_id)
    teams = _inflate_teams(connection, json.loads(draft["teams_json"]))
    summaries = [team_summary(team) for team in teams]
    return render_template("result.html", draft=draft, teams=teams, summaries=summaries)


@bp.post("/result/<draft_id>/regenerate")
def regenerate(draft_id: str):
    connection = get_db()
    draft = _load_owned_draft(connection, draft_id)
    member_ids = json.loads(draft["member_ids_json"])
    members = _members_from_ids(connection, member_ids)
    settings = json.loads(draft["settings_json"])
    settings["seed"] = secrets.randbits(63)
    teams = build_teams(
        members,
        mode=settings["mode"],
        value=int(settings["value"]),
        weights=settings["weights"],
        pair_counts=_history_pairs(connection),
        seed=settings["seed"],
    )
    team_ids = [[member["id"] for member in team] for team in teams]
    connection.execute(
        """
        UPDATE drafts
        SET settings_json=?, teams_json=?, output_text=?, updated_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (
            json.dumps(settings, ensure_ascii=False),
            json.dumps(team_ids),
            format_teams(teams, draft["event_name"]),
            draft_id,
        ),
    )
    connection.commit()
    return redirect(url_for("web.result", draft_id=draft_id))


@bp.post("/result/<draft_id>/save")
def save_result(draft_id: str):
    connection = get_db()
    draft = _load_owned_draft(connection, draft_id)
    cursor = connection.execute(
        """
        INSERT INTO formations (event_name, settings_json, teams_json, output_text, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            draft["event_name"], draft["settings_json"], draft["teams_json"],
            draft["output_text"], _now_jst(),
        ),
    )
    formation_id = cursor.lastrowid
    for team in json.loads(draft["teams_json"]):
        for first, second in combinations(sorted(team), 2):
            connection.execute(
                "INSERT OR IGNORE INTO formation_pairs (formation_id, member_a, member_b) VALUES (?, ?, ?)",
                (formation_id, first, second),
            )
    connection.execute("DELETE FROM drafts WHERE id = ?", (draft_id,))
    connection.commit()
    session.pop("draft_id", None)
    flash("チーム編成を履歴に保存しました。")
    return redirect(url_for("web.index"))


@bp.get("/history")
def history():
    rows = get_db().execute("SELECT * FROM formations ORDER BY id DESC").fetchall()
    return render_template("history.html", formations=rows)


@bp.get("/members")
def members():
    query = normalize_text(request.args.get("q"))
    connection = get_db()
    if query:
        wildcard = f"%{query}%"
        rows = connection.execute(
            """
            SELECT * FROM members
            WHERE line_name LIKE ? OR full_name LIKE ? OR department LIKE ? OR student_id LIKE ?
            ORDER BY line_name
            """,
            (wildcard, wildcard, wildcard, wildcard),
        ).fetchall()
    else:
        rows = connection.execute("SELECT * FROM members ORDER BY line_name").fetchall()
    return render_template("members.html", members=rows, query=query)


@bp.post("/members/import")
def members_import():
    upload = request.files.get("csv_file")
    if not upload or not upload.filename:
        flash("CSVファイルを選択してください。", "error")
        return redirect(url_for("web.members"))
    try:
        result = import_members(get_db(), upload.read())
    except ValueError as error:
        flash(str(error), "error")
        return redirect(url_for("web.members"))
    flash(f"{result.imported}件を読み込み、{result.skipped}件を除外しました。")
    for warning in result.warnings[:10]:
        flash(warning, "warning")
    if len(result.warnings) > 10:
        flash(f"ほか{len(result.warnings) - 10}件の注意があります。", "warning")
    return redirect(url_for("web.members"))


@bp.get("/members/export.csv")
def members_export():
    rows = get_db().execute("SELECT * FROM members ORDER BY line_name").fetchall()
    output = io.StringIO()
    fieldnames = [
        "LINEの名前", "名前", "学部", "学籍番号", "回生", "バレーボール経験",
        "出身地(都道府県)", "誕生日", "性別", "役職",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    def safe(value):
        text = str(value if value is not None else "")
        return "'" + text if text.startswith(("=", "+", "-", "@")) else text

    for row in rows:
        writer.writerow({key: safe(value) for key, value in {
            "LINEの名前": row["line_name"],
            "名前": row["full_name"],
            "学部": row["department"],
            "学籍番号": row["student_id"],
            "回生": row["grade"] if row["grade"] is not None else "",
            "バレーボール経験": row["experience"],
            "出身地(都道府県)": row["birthplace"],
            "誕生日": row["birthday"],
            "性別": row["gender"],
            "役職": row["role"],
        }.items()})
    content = ("\ufeff" + output.getvalue()).encode("utf-8")
    return send_file(
        io.BytesIO(content),
        mimetype="text/csv; charset=utf-8",
        as_attachment=True,
        download_name="members.csv",
    )


def _optional_int(value: str):
    value = normalize_text(value)
    if not value:
        return None
    try:
        return int(value)
    except ValueError as error:
        raise ValueError("回生は半角数字で入力してください。") from error


def _optional_float(value: str) -> float:
    value = normalize_text(value)
    if not value:
        return 0.0
    try:
        return float(value)
    except ValueError as error:
        raise ValueError("経験年数は数字で入力してください。") from error


@bp.route("/interview", methods=["GET", "POST"])
def interview():
    if request.method == "POST":
        line_name = normalize_text(request.form.get("line_name"))
        if not line_name:
            flash("LINEの名前は必須です。", "error")
            return render_template("interview.html", form=request.form, external_url=current_app.config["INTERVIEW_FORM_URL"]), 400
        try:
            grade = _optional_int(request.form.get("grade", ""))
            experience = _optional_float(request.form.get("experience", ""))
        except ValueError as error:
            flash(str(error), "error")
            return render_template("interview.html", form=request.form, external_url=current_app.config["INTERVIEW_FORM_URL"]), 400

        member = {
            "line_name": line_name,
            "line_key": normalize_key(line_name),
            "full_name": normalize_text(request.form.get("full_name")),
            "department": normalize_text(request.form.get("department")),
            "student_id": normalize_text(request.form.get("student_id")),
            "grade": grade,
            "experience": experience,
            "birthplace": normalize_text(request.form.get("birthplace")),
            "birthday": normalize_text(request.form.get("birthday")),
            "gender": normalize_text(request.form.get("gender")),
            "role": normalize_text(request.form.get("role")),
            "source_json": "{}",
        }
        connection = get_db()
        connection.execute(
            """
            INSERT INTO members (
                line_name, line_key, full_name, department, student_id, grade,
                experience, birthplace, birthday, gender, role, source_json
            ) VALUES (
                :line_name, :line_key, :full_name, :department, :student_id, :grade,
                :experience, :birthplace, :birthday, :gender, :role, :source_json
            )
            ON CONFLICT(line_key) DO UPDATE SET
                line_name=excluded.line_name, full_name=excluded.full_name,
                department=excluded.department, student_id=excluded.student_id,
                grade=excluded.grade, experience=excluded.experience,
                birthplace=excluded.birthplace, birthday=excluded.birthday,
                gender=excluded.gender, role=excluded.role,
                updated_at=CURRENT_TIMESTAMP
            """,
            member,
        )
        connection.commit()
        flash(f"『{line_name}』を会員リストに保存しました。")
        return redirect(url_for("web.interview"))

    return render_template("interview.html", form={}, external_url=current_app.config["INTERVIEW_FORM_URL"])


def _client_id() -> str:
    if "client_id" not in session:
        session["client_id"] = secrets.token_urlsafe(18)
    return session["client_id"]


@bp.route("/api-key", methods=["GET", "POST"])
def api_key():
    client_id = _client_id()
    if request.method == "POST":
        action = request.form.get("action", "save")
        if action == "clear":
            _api_keys.pop(client_id, None)
            flash("APIキーをメモリから削除しました。")
        else:
            key = request.form.get("api_key", "").strip()
            if not key:
                flash("APIキーを入力してください。", "error")
            else:
                _api_keys[client_id] = key
                flash("APIキーを現在のサーバー実行中だけ保持しました。")
        return redirect(url_for("web.api_key"))
    return render_template("api_key.html", key_saved=client_id in _api_keys)


@bp.get("/health")
def health() -> Response:
    return Response("ok", mimetype="text/plain")
