from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
from dataclasses import dataclass, field


def normalize_text(value: object) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip()


def normalize_key(value: object) -> str:
    value = normalize_text(value).lower()
    return re.sub(r"[\s\u3000()（）・:：?？_\-/]+", "", value)


FIELD_ALIASES = {
    "line_name": ["LINEの名前", "LINE の名前", "LINE名", "LINE表示名", "ラインの名前", "ライン名"],
    "full_name": ["名前", "氏名", "フルネーム", "名前（フルネーム・漢字）"],
    "department": ["学部", "所属学部"],
    "student_id": ["学籍番号", "学生番号"],
    "grade": ["回生", "学年"],
    "experience": ["バレーボール経験", "バレーボール経験年数", "バレー経験", "経験年数"],
    "birthplace": ["出身地(都道府県)", "出身地（都道府県）", "出身地", "都道府県"],
    "birthday": ["誕生日", "生年月日"],
    "gender": ["性別", "ジェンダー"],
    "role": ["役職"],
}


def _find_header(fieldnames: list[str], aliases: list[str]) -> str | None:
    normalized = {normalize_key(header): header for header in fieldnames if header}
    for alias in aliases:
        exact = normalized.get(normalize_key(alias))
        if exact:
            return exact
    for alias in sorted(aliases, key=len, reverse=True):
        alias_key = normalize_key(alias)
        for key, original in normalized.items():
            if alias_key and alias_key in key:
                return original
    return None


def _number(value: object, *, integer: bool = False):
    text = normalize_text(value).replace(",", "")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None if integer else 0.0
    number = float(match.group())
    return int(number) if integer else number


def decode_csv(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "cp932", "utf-8"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("CSVの文字コードを判定できません。UTF-8またはShift_JISで保存してください。")


@dataclass
class ImportResult:
    imported: int = 0
    skipped: int = 0
    warnings: list[str] = field(default_factory=list)


def import_members(connection, raw: bytes) -> ImportResult:
    text = decode_csv(raw)
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
    except csv.Error:
        dialect = csv.excel

    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    fieldnames = [name or "" for name in (reader.fieldnames or [])]
    if not fieldnames:
        raise ValueError("CSVに見出し行がありません。")

    headers = {
        field: _find_header(fieldnames, aliases)
        for field, aliases in FIELD_ALIASES.items()
    }
    if not headers["line_name"]:
        raise ValueError("『LINEの名前』列が見つかりません。")

    result = ImportResult()
    seen: set[str] = set()
    for row_number, row in enumerate(reader, start=2):
        def cell(field: str) -> str:
            header = headers.get(field)
            return normalize_text(row.get(header, "")) if header else ""

        line_name = cell("line_name")
        line_key = normalize_key(line_name)
        if not line_key:
            result.skipped += 1
            result.warnings.append(f"{row_number}行目：LINEの名前が空欄のため除外しました。")
            continue
        if line_key in seen:
            result.skipped += 1
            result.warnings.append(f"{row_number}行目：LINEの名前『{line_name}』がCSV内で重複しています。")
            continue
        seen.add(line_key)

        member = {
            "line_name": line_name,
            "line_key": line_key,
            "full_name": cell("full_name"),
            "department": cell("department"),
            "student_id": cell("student_id"),
            "grade": _number(cell("grade"), integer=True),
            "experience": _number(cell("experience")) or 0.0,
            "birthplace": cell("birthplace"),
            "birthday": cell("birthday"),
            "gender": cell("gender"),
            "role": cell("role"),
            "source_json": json.dumps(row, ensure_ascii=False),
        }
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
                line_name=excluded.line_name,
                full_name=excluded.full_name,
                department=excluded.department,
                student_id=excluded.student_id,
                grade=excluded.grade,
                experience=excluded.experience,
                birthplace=excluded.birthplace,
                birthday=excluded.birthday,
                gender=excluded.gender,
                role=excluded.role,
                source_json=excluded.source_json,
                updated_at=CURRENT_TIMESTAMP
            """,
            member,
        )
        result.imported += 1

    connection.commit()
    return result
