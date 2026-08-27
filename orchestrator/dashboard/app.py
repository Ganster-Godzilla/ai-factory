"""Dashboard Flask 应用工厂。测试可注入 tmp pool。"""
from __future__ import annotations

from pathlib import Path

from flask import Flask, render_template

from orchestrator.dashboard import views


def create_app(pool_dir: Path, cfg: dict) -> Flask:
    app = Flask(__name__)
    app.config["POOL"] = Path(pool_dir)
    app.config["CFG"] = cfg

    @app.get("/")
    def index():
        return render_template("index.html", **views.overview_data(
            app.config["POOL"], app.config["CFG"]))

    return app
