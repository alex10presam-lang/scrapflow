"""Fábrica Flask: mantém validação, persistência e HTTP separados."""

from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit
from zipfile import ZipFile

from flask import Flask, jsonify, render_template, request, send_file
from werkzeug.exceptions import RequestEntityTooLarge

from .pipeline import InputError, SCHEMAS, consolidate, read_table, summarize
from .reports import workbook_report
from .storage import RunStore
from .automation import Automation

ROOT = Path(__file__).resolve().parent.parent


def sample_data():
    return consolidate(
        {
            name: read_table((ROOT / "examples" / f"{name}.csv").read_bytes(), f"{name}.csv", name)
            for name in SCHEMAS
        }
    )


def create_app(config=None):
    app = Flask(
        __name__, template_folder=str(ROOT / "templates"), static_folder=str(ROOT / "static")
    )
    app.config.update(
        MAX_CONTENT_LENGTH=5 * 1024 * 1024, DATABASE=ROOT / "instance" / "scrapflow.sqlite3"
    )
    if config:
        app.config.update(config)
    store = RunStore(app.config["DATABASE"])
    app.extensions["runs"] = store
    automation = Automation(
        store,
        app.config.get("AUTOMATION_ROOT", Path(app.config["DATABASE"]).parent / "exportacoes"),
        app.config.get("AUTOMATION_EXAMPLES", ROOT / "examples"),
        **({"sleep": app.config["AUTOMATION_SLEEP"]} if "AUTOMATION_SLEEP" in app.config else {}),
    )
    app.extensions["automation"] = automation

    @app.before_request
    def local_origin():
        if request.method == "POST":
            origin = request.headers.get("Origin")
            if request.headers.get("Sec-Fetch-Site") == "cross-site" or (
                origin and urlsplit(origin).netloc != request.host
            ):
                return (
                    jsonify(error="Abra a aplicação no endereço local para processar arquivos."),
                    403,
                )

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; script-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(InputError)
    def invalid(error):
        return jsonify(error=str(error)), 422

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(error):
        return jsonify(error="O lote excede o limite de 5 MB."), 413

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/dashboard")
    def dashboard():
        run_id = request.args.get("run")
        run = store.get(run_id)
        if run_id and run is None:
            return jsonify(error="Execução não encontrada."), 404
        preview = run is None
        dataset = sample_data() if preview else run["dataset"]
        return jsonify(
            summary=summarize(dataset, request.args.get("line", "")),
            preview=preview,
            run=None if preview else {key: run[key] for key in ("id", "created_at", "source")},
        )

    @app.get("/api/runs")
    def history():
        return jsonify(runs=store.list())

    @app.post("/api/runs/demo")
    def demo():
        run = store.save(sample_data(), "demo")
        return jsonify(id=run["id"]), 201

    @app.post("/api/runs")
    def upload():
        if set(request.files) != set(SCHEMAS) or any(
            len(request.files.getlist(name)) != 1 for name in SCHEMAS
        ):
            raise InputError("Envie um arquivo de produtos, um de produção e um de perdas.")
        tables = {
            name: read_table(request.files[name].read(), request.files[name].filename or "", name)
            for name in SCHEMAS
        }
        run = store.save(consolidate(tables), "upload")
        return jsonify(id=run["id"]), 201

    @app.get("/api/runs/<run_id>/report")
    def report(run_id):
        run = store.get(run_id)
        if run is None:
            return jsonify(error="Execução não encontrada."), 404
        return send_file(
            workbook_report(run),
            as_attachment=True,
            download_name=f"scrapflow-{run_id[:8]}.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    @app.get("/api/examples")
    def examples():
        stream = BytesIO()
        with ZipFile(stream, "w") as archive:
            for name in SCHEMAS:
                archive.write(ROOT / "examples" / f"{name}.csv", f"{name}.csv")
        stream.seek(0)
        return send_file(
            stream,
            as_attachment=True,
            download_name="scrapflow-exemplos.zip",
            mimetype="application/zip",
        )

    @app.get("/api/automation")
    def automation_status():
        return jsonify(
            mode="demo",
            jobs=automation.jobs.list(),
            schedule={
                "active": False,
                "timezone": "America/Manaus",
                "description": "Segunda a sexta às 09h, após importar e ativar o fluxo n8n opcional.",
            },
        )

    @app.post("/api/automation/jobs")
    def start_automation():
        args = request.get_json(silent=True)
        if not isinstance(args, dict) or set(args) - {"scenario", "trigger"}:
            raise InputError("Envie um objeto JSON com cenário e disparo válidos.")
        job, created = automation.start(
            args.get("scenario", "normal"), args.get("trigger", "manual")
        )
        return jsonify(job=job, reused=not created), 202 if job["status"] == "running" else 200

    @app.get("/api/automation/jobs/<job_id>")
    def automation_job(job_id):
        job = automation.jobs.get(job_id)
        if job is None:
            return jsonify(error="Execução dos bots não encontrada."), 404
        return jsonify(job=job)

    @app.get("/api/automation/jobs/<job_id>/archive")
    def automation_archive(job_id):
        job = automation.jobs.get(job_id)
        if job is None:
            return jsonify(error="Execução dos bots não encontrada."), 404
        if job["status"] == "running":
            return jsonify(error="Aguarde a conclusão antes de baixar a conferência."), 409
        folder = automation.folder(job)
        stream = BytesIO()
        with ZipFile(stream, "w") as archive:
            if folder.is_dir():
                for path in sorted(folder.rglob("*")):
                    if (
                        path.is_file()
                        and path.resolve().is_relative_to(folder)
                        and path.suffix in {".csv", ".xlsx", ".json", ".txt"}
                    ):
                        archive.write(path, path.relative_to(folder).as_posix())
        stream.seek(0)
        return send_file(
            stream,
            as_attachment=True,
            download_name=f"scrapflow-conferencia-{job_id[:8]}.zip",
            mimetype="application/zip",
        )

    @app.get("/api/automation/workflow")
    def automation_workflow():
        return send_file(
            ROOT / "integrations" / "n8n-demo.workflow.json",
            as_attachment=True,
            download_name="scrapflow-bots-demo.workflow.json",
            mimetype="application/json",
        )

    return app
