from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from io import BytesIO
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from openpyxl import load_workbook
from scrapflow import ROOT, create_app, sample_data
from scrapflow.automation import Automation, ZONE, source_workbook
from scrapflow.pipeline import InputError, SCHEMAS, read_table
from scrapflow.reports import workbook_report
from scrapflow.storage import RunStore


class BotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runs = RunStore(self.root / "runs.db")
        self.bots = Automation(
            self.runs, self.root / "exportacoes", ROOT / "examples", sleep=lambda _: None
        )

    def test_normal_checks_real_files_and_cost_before_publishing(self):
        job, created = self.bots.start(background=False)
        self.assertTrue(created)
        self.assertEqual(job["status"], "done")
        self.assertEqual(job["checks"]["cost_cents"], 747170)
        self.assertEqual(job["checks"]["lost"], 400)
        self.assertEqual(
            {n: v["saved"] for n, v in job["checks"]["sources"].items()},
            {"produtos": 6, "producao": 12, "perdas": 36},
        )
        folder = self.bots.folder(job)
        for name in SCHEMAS:
            self.assertEqual(
                hashlib.sha256((folder / "originais" / f"{name}.csv").read_bytes()).hexdigest(),
                job["sources"][name]["sha256"],
            )
        self.assertTrue((folder / "resumo.txt").is_file())
        self.assertTrue((folder / "conferencia.json").is_file())
        self.assertEqual(self.runs.get()["source"], "bots")

    def test_sources_really_execute_in_parallel(self):
        barrier = threading.Barrier(3)
        threads = set()

        def read(*args):
            threads.add(threading.get_ident())
            barrier.wait(timeout=4)
            return read_table(*args)

        with patch("scrapflow.automation.read_table", side_effect=read):
            job, _ = self.bots.start(background=False)
        self.assertEqual(job["status"], "done")
        self.assertEqual(len(threads), 3)

    def test_temporary_failure_recovers_without_duplicating_run(self):
        job, _ = self.bots.start("temporary_failure", background=False)
        self.assertEqual(job["status"], "done")
        self.assertEqual(job["sources"]["producao"]["attempt"], 2)
        self.assertEqual(len(self.runs.list()), 1)
        self.bots.execute(job["id"])
        self.assertEqual(len(self.runs.list()), 1)

    def test_invalid_batch_preserves_previous_run_and_raw_files(self):
        previous = self.runs.save(sample_data(), "demo")
        job, _ = self.bots.start("invalid_batch", background=False)
        self.assertEqual(job["status"], "failed")
        self.assertIsNone(job["run_id"])
        self.assertIn("ordem não cadastrada", job["error"])
        self.assertEqual(self.runs.get()["id"], previous["id"])
        self.assertEqual(len(self.runs.list()), 1)
        self.assertTrue((self.bots.folder(job) / "originais/perdas.csv").exists())

    def test_missing_source_stops_after_three_attempts(self):
        examples = self.root / "examples"
        examples.mkdir()
        for name in ("produtos", "perdas"):
            (examples / f"{name}.csv").write_bytes((ROOT / "examples" / f"{name}.csv").read_bytes())
        bots = Automation(self.runs, self.root / "out", examples, sleep=lambda _: None)
        job, _ = bots.start(background=False)
        self.assertEqual(job["status"], "failed")
        self.assertEqual(job["sources"]["producao"]["attempt"], 3)
        self.assertEqual(self.runs.list(), [])

    def test_tampered_saved_source_blocks_publication(self):
        original = source_workbook

        def tamper(tables):
            return original({**tables, "produtos": tables["produtos"][:-1]})

        with patch("scrapflow.automation.source_workbook", side_effect=tamper):
            job, _ = self.bots.start(background=False)
        self.assertEqual(job["status"], "failed")
        self.assertEqual(self.runs.list(), [])

    def test_tampered_report_cost_blocks_publication(self):
        def tamper(run):
            book = load_workbook(workbook_report(run))
            book["Resumo"]["B8"] = 0
            stream = BytesIO()
            book.save(stream)
            book.close()
            return stream

        with patch("scrapflow.automation.workbook_report", side_effect=tamper):
            job, _ = self.bots.start(background=False)
        self.assertEqual(job["status"], "failed")
        self.assertIn("custo divergente", job["error"])
        self.assertEqual(self.runs.list(), [])

    def test_daily_schedule_is_deduplicated_after_restart_and_changes_date(self):
        current = datetime(2026, 12, 31, 9, tzinfo=ZONE)
        self.bots.clock = lambda: current
        first, _ = self.bots.start(trigger="schedule", background=False)
        other = Automation(
            self.runs, self.root / "exportacoes", ROOT / "examples", clock=lambda: current
        )
        same, created = other.start(trigger="schedule", background=False)
        self.assertFalse(created)
        self.assertEqual(same["id"], first["id"])
        self.assertEqual(len(self.runs.list()), 1)
        current += timedelta(days=1)
        following, _ = other.start(trigger="schedule", background=False)
        self.assertNotEqual(first["id"], following["id"])
        self.assertTrue(following["folder"].startswith("2027/01/01/"))

    def test_concurrent_requests_reuse_one_active_job(self):
        with patch.object(self.bots, "launch"):
            with ThreadPoolExecutor(max_workers=4) as pool:
                responses = list(pool.map(lambda _: self.bots.start(), range(4)))
        self.assertEqual(sum(created for _, created in responses), 1)
        self.assertEqual(len({job["id"] for job, _ in responses}), 1)

    def test_publish_is_atomic_and_idempotent(self):
        job, _ = self.bots.start(background=False)
        self.bots.jobs.publish(job["id"], sample_data(), {"finished_at": "2026-01-01T00:00:00Z"})
        self.assertEqual(len(self.runs.list()), 1)

    def test_bot_run_is_stored_in_utc_and_is_latest_after_manual_run(self):
        manual = self.runs.save(sample_data(), "demo")
        instant = datetime.fromisoformat(manual["created_at"]).astimezone(ZONE) + timedelta(
            seconds=1
        )
        self.bots.clock = lambda: instant
        job, _ = self.bots.start(background=False)
        self.assertEqual(job["status"], "done")
        self.assertEqual(self.runs.get()["id"], job["id"])
        self.assertEqual(self.runs.list()[0]["id"], job["id"])
        self.assertTrue(self.runs.get()["created_at"].endswith("+00:00"))

    def test_schedule_reusing_active_manual_job_does_not_publish_again(self):
        with patch.object(self.bots, "launch"):
            manual, _ = self.bots.start()
            scheduled, created = self.bots.start(trigger="schedule")
        self.assertFalse(created)
        self.assertEqual(manual["id"], scheduled["id"])
        self.bots.execute(manual["id"])
        repeated, created = self.bots.start(trigger="schedule", background=False)
        self.assertFalse(created)
        self.assertEqual(repeated["id"], manual["id"])
        self.assertEqual(len(self.runs.list()), 1)

    def test_orphan_is_interrupted_and_can_start_another_job(self):
        with patch("scrapflow.automation.threading.Thread.start"):
            job, _ = self.bots.start()
        self.bots.jobs.recover(lambda _: False)
        self.assertEqual(self.bots.jobs.get(job["id"])["status"], "interrupted")
        self.assertEqual(self.runs.list(), [])
        next_job, _ = self.bots.start(background=False)
        self.assertEqual(next_job["status"], "done")

    def test_unknown_scenarios_are_rejected_and_no_paths_are_accepted(self):
        with self.assertRaises(InputError):
            self.bots.start("../../private")
        with self.assertRaises(InputError):
            self.bots.start("invalid_batch", trigger="schedule")


class BotApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE": Path(self.temp.name) / "test.db",
                "AUTOMATION_SLEEP": lambda _: None,
            }
        )
        self.client = self.app.test_client()

    def finish(self, job_id):
        for _ in range(500):
            job = self.client.get(f"/api/automation/jobs/{job_id}").json["job"]
            if job["status"] != "running":
                return job
            time.sleep(0.02)
        self.fail("Bots não terminaram no limite do teste.")

    def test_api_runs_async_and_downloads_conference(self):
        response = self.client.post("/api/automation/jobs", json={"scenario": "normal"})
        self.assertIn(response.status_code, (200, 202))
        job = self.finish(response.json["job"]["id"])
        self.assertEqual(job["status"], "done")
        archive = self.client.get(f"/api/automation/jobs/{job['id']}/archive")
        with ZipFile(BytesIO(archive.data)) as z:
            self.assertIn("relatorio.xlsx", z.namelist())
            self.assertIn("fontes.xlsx", z.namelist())
            self.assertEqual(json.loads(z.read("conferencia.json"))["cost_cents"], 747170)
        self.assertEqual(self.client.get("/api/automation").json["mode"], "demo")
        self.assertEqual(
            self.client.get(f"/api/dashboard?run={job['run_id']}").json["run"]["source"], "bots"
        )

    def test_api_rejects_bad_input_and_cross_origin(self):
        for payload in ([], {"path": "private"}, {"scenario": "unknown"}):
            self.assertEqual(
                self.client.post("/api/automation/jobs", json=payload).status_code, 422
            )
        self.assertEqual(
            self.client.post(
                "/api/automation/jobs", json={}, headers={"Origin": "https://example.com"}
            ).status_code,
            403,
        )
        self.assertEqual(self.client.get("/api/automation/jobs/unknown").status_code, 404)

    def test_workflow_and_ui_explicitly_use_synthetic_sources(self):
        response = self.client.get("/api/automation/workflow")
        workflow = json.loads(response.data)
        response.close()
        self.assertFalse(workflow["active"])
        self.assertEqual(workflow["settings"]["timezone"], "America/Manaus")
        self.assertIn("FONTES FICTÍCIAS", self.client.get("/").text)
        response = self.client.get("/static/automation.js")
        self.assertEqual(response.status_code, 200)
        response.close()
