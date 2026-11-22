from __future__ import annotations

import os
from pathlib import Path

from flask import Flask

from . import db
from .web import bp


def _load_or_create_secret(instance_path: Path) -> str:
    secret_path = instance_path / ".secret_key"
    if secret_path.exists():
        return secret_path.read_text(encoding="utf-8").strip()

    secret = os.urandom(32).hex()
    secret_path.write_text(secret, encoding="utf-8")
    return secret


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(
        __name__,
        instance_relative_config=True,
        template_folder="../templates",
        static_folder="../static",
    )
    instance_path = Path(app.instance_path)
    instance_path.mkdir(parents=True, exist_ok=True)

    app.config.from_mapping(
        SECRET_KEY=_load_or_create_secret(instance_path),
        DATABASE=str(instance_path / "team_builder.sqlite3"),
        MAX_CONTENT_LENGTH=5 * 1024 * 1024,
        INTERVIEW_FORM_URL=os.environ.get("INTERVIEW_FORM_URL", ""),
    )
    if test_config:
        app.config.update(test_config)

    db.init_app(app)
    app.register_blueprint(bp)

    with app.app_context():
        db.init_db()

    return app
