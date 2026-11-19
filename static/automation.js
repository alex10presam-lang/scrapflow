"use strict";

(() => {
  let selected = null;
  let timer;
  let posting = false;
  let loading = false;
  const statusLabel = { running: "Em execução", done: "Concluído", failed: "Publicação bloqueada", interrupted: "Interrompido" };
  const phaseLabel = { collecting: "Coletando as três fontes em paralelo…", validating: "Conferindo valores, linhas e totais nos arquivos salvos…", publishing: "Publicando o lote conferido…", done: "Lote publicado. Linhas, quantidades e custos conferidos.", failed: "A execução foi interrompida. Os lotes anteriores foram preservados.", interrupted: "A aplicação foi encerrada durante este trabalho." };
  const names = { waiting: "Aguardando", collecting: "Coletando", collected: "Coletado", retrying: "Aguardando nova tentativa", failed: "Falhou" };
  const node = (tag, className, value) => element(tag, className, value);

  function render(job) {
    const running = job?.status === "running";
    document.querySelector("#run-bots").disabled = running || posting;
    document.querySelector("#bot-scenario").disabled = running || posting;
    if (!job) return;
    document.querySelector("#bot-status").textContent = job.error || phaseLabel[job.phase] || "Consultando execução…";
    for (const name of ["produtos", "producao", "perdas"]) {
      const source = job.sources[name];
      const next = source.next_attempt_at ? ` · próxima tentativa ${dateTime(source.next_attempt_at)}` : "";
      document.querySelector(`#bot-${name}`).textContent = `${names[source.status] || source.status}${source.rows == null ? "" : ` · ${number.format(source.rows)} linhas`}${source.attempt ? ` · tentativa ${source.attempt}/3` : ""}${next}`;
      document.querySelector(`#bot-${name}`).closest("article").dataset.status = source.status;
    }
    const output = document.querySelector("#bot-result");
    output.replaceChildren();
    output.hidden = running;
    output.dataset.status = job.status;
    if (!running) {
      output.append(node("strong", "", statusLabel[job.status]));
      output.append(node("p", "", `${dateTime(job.created_at)} · duração: ${job.duration_seconds == null ? "não registrada" : number.format(job.duration_seconds) + " s"}`));
      if (job.checks) {
        for (const [name, check] of Object.entries(job.checks.sources)) {
          output.append(node("p", "", `${job.sources[name].label}: ${check.exported} coletadas = ${check.prepared} preparadas = ${check.saved} no Excel salvo.`));
        }
        output.append(node("p", "", `${number.format(job.checks.lost)} unidades perdidas · custo conferido: ${currency.format(job.checks.cost_cents / 100)}.`));
      }
      if (job.error) output.append(node("p", "", job.error));
      for (const warning of job.warnings || []) output.append(node("p", "", warning));
      output.append(node("small", "", `Arquivo local: instance/exportacoes/${job.folder}`));
    }
    const dashboard = document.querySelector("#bot-dashboard");
    dashboard.hidden = job.status !== "done";
    dashboard.onclick = async (event) => {
      event.preventDefault();
      state.run = job.run_id;
      document.querySelector("#line-filter").value = "";
      document.querySelector("#search").value = "";
      try { await loadDashboard(); location.hash = "overview"; } catch (error) { notify(error.message); }
    };
    dashboard.href = "#overview";
    const archive = document.querySelector("#bot-archive");
    archive.hidden = running;
    archive.href = `/api/automation/jobs/${encodeURIComponent(job.id)}/archive`;
  }

  async function refresh() {
    if (loading) return;
    loading = true;
    try {
      const data = await api("/api/automation");
      const current = data.jobs.find((job) => job.status === "running") || data.jobs.find((job) => job.id === selected) || data.jobs[0];
      if (current) selected = current.id;
      render(current || null);
      const history = document.querySelector("#bot-history");
      history.replaceChildren();
      if (!data.jobs.length) history.append(node("p", "empty", "Nenhuma execução dos bots registrada."));
      for (const job of data.jobs) {
        const row = node("div", "bot-history-row");
        const info = node("div", "");
        info.append(node("strong", "", `${statusLabel[job.status]} · ${job.id.slice(0, 8)}`), node("small", "", `${dateTime(job.created_at)} · ${job.trigger === "schedule" ? "Agendado" : "Manual"}`));
        const button = node("button", "button secondary", "Detalhes ↗");
        button.type = "button";
        button.addEventListener("click", () => { selected = job.id; render(job); });
        row.append(info, button); history.append(row);
      }
      clearTimeout(timer);
      timer = setTimeout(refresh, data.jobs.some((job) => job.status === "running") ? 500 : 5000);
    } catch (error) {
      document.querySelector("#bot-status").textContent = error.message;
      clearTimeout(timer); timer = setTimeout(refresh, 5000);
    } finally { loading = false; }
  }

  document.querySelector("#run-bots").addEventListener("click", async () => {
    if (posting) return;
    posting = true;
    document.querySelector("#run-bots").disabled = true;
    try {
      const result = await api("/api/automation/jobs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ scenario: document.querySelector("#bot-scenario").value, trigger: "manual" }) });
      selected = result.job.id;
      render(result.job);
      if (result.reused) notify("Uma execução já estava ativa. Acompanhando o mesmo trabalho.");
    } catch (error) { notify(error.message); }
    finally {
      posting = false;
      document.querySelector("#run-bots").disabled = false;
      document.querySelector("#bot-scenario").disabled = false;
      await refresh();
    }
  });
  refresh();
})();
