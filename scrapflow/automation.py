"""Bots executáveis de portfólio: somente fontes fictícias locais, sem acesso a ERP."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import threading
import time
from uuid import uuid4

from openpyxl import Workbook, load_workbook

from .pipeline import InputError, SCHEMAS, consolidate, read_table, summarize
from .reports import workbook_report
from .storage import AutomationStore

ZONE = timezone(timedelta(hours=-4), "America/Manaus")
SCENARIOS = {"normal", "temporary_failure", "invalid_batch"}
LABELS = {
    "produtos": "Catálogo de produtos",
    "producao": "Ordens de produção",
    "perdas": "Registros de perdas",
}


class TemporarySourceError(Exception):
    pass


def alive(pid):
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() == 5
        try:
            code = wintypes.DWORD()
            kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def write_json(path, value):
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def source_workbook(tables):
    book = Workbook()
    book.remove(book.active)
    for name in SCHEMAS:
        rows = tables[name]
        sheet = book.create_sheet(name)
        sheet.append(list(SCHEMAS[name]))
        for row in rows:
            sheet.append([row[key] for key in SCHEMAS[name]])
            for cell in sheet[sheet.max_row]:
                cell.data_type = "s"  # Preserva códigos e impede fórmulas nos textos.
        sheet.freeze_panes = "A2"
    stream = BytesIO()
    book.save(stream)
    book.close()
    return stream.getvalue()


def verify_outputs(tables, dataset, sources_content, report_content):
    """Relê ambos os XLSX antes da publicação: valores, linhas e totais."""
    checks = {}
    book = load_workbook(BytesIO(sources_content), read_only=True, data_only=False)
    try:
        for name, rows in tables.items():
            saved = list(book[name].iter_rows(values_only=True))
            expected = [tuple(row[key] for key in SCHEMAS[name]) for row in rows]
            if saved[0] != SCHEMAS[name] or saved[1:] != expected:
                raise InputError(f"Conferência de {name}: o arquivo salvo diverge da fonte.")
            checks[name] = {
                "exported": len(rows),
                "prepared": len(rows),
                "saved": len(saved) - 1,
                "status": "checked",
            }
    finally:
        book.close()
    summary = summarize(dataset)
    book = load_workbook(BytesIO(report_content), read_only=True, data_only=False)
    try:
        records = list(book["Perdas"].iter_rows(min_row=2, values_only=True))
        cents = lambda value: int((Decimal(str(value)) * 100).quantize(Decimal("1")))
        if (
            len(records) != len(dataset["records"])
            or sum(row[7] for row in records) != summary["lost"]
        ):
            raise InputError("Conferência do relatório: linhas ou quantidades divergentes.")
        if (
            sum(cents(row[8]) for row in records) != summary["cost_cents"]
            or cents(book["Resumo"]["B8"].value) != summary["cost_cents"]
        ):
            raise InputError("Conferência do relatório: custo divergente.")
    finally:
        book.close()
    return {
        "sources": checks,
        "report_rows": len(records),
        "lost": summary["lost"],
        "cost_cents": summary["cost_cents"],
        "status": "checked",
    }


class Automation:
    def __init__(self, runs, root, examples, *, sleep=time.sleep, clock=None):
        self.jobs = AutomationStore(runs)
        self.root = Path(root).resolve()
        self.examples = Path(examples)
        self.sleep = sleep
        self.clock = clock or (lambda: datetime.now(ZONE))
        self.jobs.recover(alive)

    def start(self, scenario="normal", trigger="manual", *, background=True):
        if scenario not in SCENARIOS or trigger not in {"manual", "schedule"}:
            raise InputError("Escolha um cenário e um disparo válidos.")
        if trigger == "schedule" and scenario != "normal":
            raise InputError("O agendamento utiliza apenas o cenário normal.")
        now = self.clock()
        job_id = uuid4().hex
        folder = now.strftime("%Y/%m/%d/") + now.strftime("%H%M%S-") + job_id
        job = {
            "id": job_id,
            "status": "running",
            "phase": "collecting",
            "scenario": scenario,
            "trigger": trigger,
            "created_at": now.isoformat(),
            "finished_at": None,
            "duration_seconds": None,
            "run_id": None,
            "folder": folder,
            "error": None,
            "warnings": [],
            "checks": None,
            "sources": {
                name: {"label": LABELS[name], "status": "waiting", "attempt": 0, "rows": None}
                for name in SCHEMAS
            },
        }
        day_key = now.date().isoformat() if trigger == "schedule" else None
        job, created = self.jobs.start(job, day_key, os.getpid())
        if created:
            if background:
                try:
                    self.launch(job["id"])
                except RuntimeError:
                    self.jobs.patch(
                        job["id"],
                        status="failed",
                        phase="failed",
                        error="Não foi possível iniciar os bots.",
                    )
                    raise InputError("Não foi possível iniciar os bots. Tente novamente.") from None
            else:
                self.execute(job["id"])
        return self.jobs.get(job["id"]), created

    def launch(self, job_id):
        threading.Thread(target=self.execute, args=(job_id,), daemon=True).start()

    def folder(self, job):
        folder = (self.root / job["folder"]).resolve()
        if not folder.is_relative_to(self.root) or folder == self.root:
            raise InputError("Pasta da execução inválida.")
        return folder

    def collect(self, job, name, cancelled):
        folder = self.folder(job)
        for attempt in range(1, 4):
            if cancelled.is_set():
                raise InputError("Coleta cancelada após falha em outra fonte.")
            self.jobs.patch(
                job["id"],
                sources={
                    name: {
                        "label": LABELS[name],
                        "status": "collecting",
                        "attempt": attempt,
                        "rows": None,
                    }
                },
            )
            try:
                if job["scenario"] == "temporary_failure" and name == "producao" and attempt == 1:
                    raise TemporarySourceError(
                        "Indisponibilidade temporária simulada na fonte de produção."
                    )
                with (self.examples / f"{name}.csv").open("rb") as source:
                    content = source.read(5 * 1024 * 1024 + 1)
                if job["scenario"] == "invalid_batch" and name == "perdas":
                    content = b"id,ordem,data,quantidade,motivo\nDEMO-INVALIDO,ORDEM-INEXISTENTE,2026-10-01,1,Teste controlado\n"
                if len(content) > 5 * 1024 * 1024:
                    raise InputError("Fonte excede o limite de 5 MB.")
                target = folder / "originais" / f"{name}.csv"
                with target.open("xb") as stream:
                    stream.write(content)
                digest = hashlib.sha256(content).hexdigest()
                if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                    raise InputError("Cópia da fonte diverge do original.")
                rows = read_table(content, f"{name}.csv", name)
                self.jobs.patch(
                    job["id"],
                    sources={
                        name: {
                            "label": LABELS[name],
                            "status": "collected",
                            "attempt": attempt,
                            "rows": len(rows),
                            "sha256": digest,
                        }
                    },
                )
                return name, rows
            except (TemporarySourceError, OSError):
                if attempt == 3:
                    self.jobs.patch(
                        job["id"],
                        sources={
                            name: {
                                "label": LABELS[name],
                                "status": "failed",
                                "attempt": attempt,
                                "rows": None,
                            }
                        },
                    )
                    raise InputError(f"{LABELS[name]} indisponível após três tentativas.") from None
                delay = 2 * attempt
                self.jobs.patch(
                    job["id"],
                    sources={
                        name: {
                            "label": LABELS[name],
                            "status": "retrying",
                            "attempt": attempt,
                            "rows": None,
                            "next_attempt_at": (
                                self.clock() + timedelta(seconds=delay)
                            ).isoformat(),
                        }
                    },
                )
                if self.sleep is time.sleep:
                    if cancelled.wait(delay):
                        raise InputError("Coleta cancelada após falha em outra fonte.")
                else:
                    self.sleep(delay)
        raise InputError("A coleta não foi concluída.")

    def execute(self, job_id):
        job = self.jobs.get(job_id)
        if job["status"] != "running":
            return
        folder = self.folder(job)
        cancelled = threading.Event()
        try:
            (folder / "originais").mkdir(parents=True, exist_ok=False)
            tables = {}
            with ThreadPoolExecutor(max_workers=3) as pool:
                futures = [pool.submit(self.collect, job, name, cancelled) for name in SCHEMAS]
                try:
                    for future in as_completed(futures):
                        name, rows = future.result()
                        tables[name] = rows
                except Exception:
                    cancelled.set()
                    raise
            self.jobs.patch(job_id, phase="validating")
            dataset = consolidate(tables)
            sources_content = source_workbook(tables)
            run = {
                "id": job_id,
                "created_at": job["created_at"],
                "source": "bots",
                "dataset": dataset,
            }
            report_content = workbook_report(run).getvalue()
            for name, content in (
                ("fontes.xlsx", sources_content),
                ("relatorio.xlsx", report_content),
            ):
                with (folder / name).open("xb") as stream:
                    stream.write(content)
            checks = verify_outputs(
                tables,
                dataset,
                (folder / "fontes.xlsx").read_bytes(),
                (folder / "relatorio.xlsx").read_bytes(),
            )
            write_json(folder / "conferencia.json", checks)
            finished = self.clock()
            final = {
                "finished_at": finished.isoformat(),
                "duration_seconds": max(
                    0,
                    round(
                        (finished - datetime.fromisoformat(job["created_at"])).total_seconds(), 3
                    ),
                ),
                "checks": checks,
                "summary": {
                    key: value for key, value in summarize(dataset).items() if key != "records"
                },
            }
            self.jobs.patch(job_id, phase="publishing", **final)
            self.jobs.publish(job_id, dataset, final)
        except Exception as error:
            cancelled.set()
            message = (
                str(error)
                if isinstance(error, InputError)
                else "A execução foi interrompida. Confira as fontes e tente novamente."
            )
            finished = self.clock()
            self.jobs.patch(
                job_id,
                status="failed",
                phase="failed",
                finished_at=finished.isoformat(),
                duration_seconds=max(
                    0,
                    round(
                        (finished - datetime.fromisoformat(job["created_at"])).total_seconds(), 3
                    ),
                ),
                error=message,
            )
        # Falha no arquivo de resumo não desfaz uma publicação já confirmada no SQLite.
        try:
            state = self.jobs.get(job_id)
            write_json(folder / "resumo.json", state)
            lines = [
                "SCRAPFLOW · BOTS DE DEMONSTRAÇÃO",
                "Fontes exclusivamente fictícias.",
                f"Execução: {job_id}",
                f"Resultado: {state['status']}",
                f"Início: {state['created_at']}",
                f"Fim: {state.get('finished_at')}",
                f"Duração (s): {state.get('duration_seconds')}",
            ]
            lines += [
                f"{source['label']}: {source.get('rows')} linhas; tentativa {source['attempt']}."
                for source in state["sources"].values()
            ]
            if state.get("error"):
                lines.append(state["error"])
            (folder / "resumo.txt").write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
        except OSError:
            self.jobs.patch(
                job_id, warnings=["Não foi possível gravar o resumo na pasta de conferência."]
            )
