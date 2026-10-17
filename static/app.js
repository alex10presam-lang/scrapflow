"use strict";

const $ = (selector) => document.querySelector(selector);
const number = new Intl.NumberFormat("pt-BR");
const currency = new Intl.NumberFormat("pt-BR", {
  style: "currency",
  currency: "BRL",
});
const state = { run: null, summary: null, page: 0, busy: false, request: 0 };
const pageSize = 8;
let toastTimer;

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function notify(message) {
  clearTimeout(toastTimer);
  $("#toast").textContent = message;
  $("#toast").hidden = false;
  toastTimer = setTimeout(() => {
    $("#toast").hidden = true;
  }, 8000);
}

async function api(url, options = {}) {
  const response = await fetch(url, options);
  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error(
      "O servidor não retornou uma resposta válida. Verifique o terminal.",
    );
  }
  if (!response.ok)
    throw new Error(data.error || "Não foi possível concluir a operação.");
  return data;
}

function dateLabel(value) {
  const [year, month, day] = value.split("-");
  return `${day}/${month}/${year}`;
}

function dateTime(value) {
  return new Date(value).toLocaleString("pt-BR", {
    dateStyle: "short",
    timeStyle: "short",
  });
}

function setBusy(busy) {
  state.busy = busy;
  document.querySelectorAll(".run-demo, #upload-button").forEach((button) => {
    button.disabled = busy;
    button.setAttribute("aria-busy", String(busy));
    if (busy) {
      button.dataset.label = button.textContent;
      button.textContent = "Processando lote…";
    } else {
      button.textContent = button.dataset.label;
    }
  });
}

async function processBatch(url, options) {
  if (state.busy) return;
  setBusy(true);
  $("#upload-error").hidden = true;
  try {
    const result = await api(url, { method: "POST", ...options });
    state.run = result.id;
    $("#line-filter").value = "";
    $("#search").value = "";
    await loadDashboard();
    location.hash = "overview";
    notify("Lote consolidado. O relatório Excel já está disponível.");
  } catch (error) {
    $("#upload-error").textContent = error.message;
    $("#upload-error").hidden = false;
    notify(error.message);
  } finally {
    setBusy(false);
  }
}

async function loadDashboard() {
  const sequence = ++state.request;
  const params = new URLSearchParams();
  if (state.run) params.set("run", state.run);
  const selectedLine = $("#line-filter").value;
  if (selectedLine) params.set("line", selectedLine);
  const data = await api(`/api/dashboard?${params}`);
  if (sequence !== state.request) return;
  state.summary = data.summary;
  state.run = data.run?.id || null;
  state.page = 0;
  const summary = data.summary;
  $("#metric-cost").textContent = currency.format(summary.cost_cents / 100);
  $("#metric-rate").textContent = `${number.format(summary.rate)}%`;
  $("#metric-lost").textContent = number.format(summary.lost);
  $("#metric-orders").textContent = number.format(summary.order_count);
  $("#metric-good").textContent =
    `${number.format(summary.good)} unidades boas`;
  $("#metric-records").textContent =
    `${number.format(summary.record_count)} registros de perda`;
  $("#source-badge").textContent = data.preview
    ? "DADOS FICTÍCIOS · PRÉVIA"
    : data.run.source === "demo"
      ? "DADOS FICTÍCIOS · CONSOLIDADOS"
      : "LOTE IMPORTADO · CONSOLIDADO";
  $("#dataset-caption").textContent = data.preview
    ? "Prévia do conjunto de exemplo. Nenhuma execução salva."
    : `Lote ${data.run.id.slice(0, 8)} · processado em ${dateTime(data.run.created_at)}`;
  const filter = $("#line-filter");
  filter.replaceChildren(
    new Option("Todas as linhas", ""),
    ...summary.lines.map((line) => new Option(line, line)),
  );
  filter.value = selectedLine;
  const report = $("#report-link");
  report.classList.toggle("disabled", data.preview);
  report.setAttribute("aria-disabled", String(data.preview));
  if (data.run) report.href = `/api/runs/${data.run.id}/report`;
  else report.removeAttribute("href");
  renderReasons(summary.reasons);
  renderTrend(summary.daily);
  renderRecords();
}

function renderReasons(reasons) {
  const container = $("#reasons");
  container.replaceChildren();
  if (!reasons.length) {
    container.append(element("p", "empty", "Nenhuma perda nesta linha."));
    return;
  }
  const max = Math.max(1, ...reasons.map((reason) => reason.cents));
  reasons.slice(0, 5).forEach((reason, index) => {
    const row = element("div", "reason");
    const info = element("div", "reason-info");
    const name = element("span", "reason-name");
    name.append(
      element("span", "rank", String(index + 1).padStart(2, "0")),
      document.createTextNode(reason.name),
    );
    info.append(
      name,
      element("span", "reason-amount", currency.format(reason.cents / 100)),
    );
    const track = element("div", "reason-track");
    const bar = element("div", "reason-bar");
    bar.style.setProperty("--amount", `${(reason.cents / max) * 100}%`);
    track.append(bar);
    row.append(info, track);
    container.append(row);
  });
}

function renderTrend(days) {
  const container = $("#trend");
  container.replaceChildren();
  // Exibe até 14 datas; o relatório e a tabela mantêm todos os registros.
  const visible = days.slice(-14);
  if (!visible.length) {
    container.append(element("p", "empty", "Nenhum registro no recorte."));
    return;
  }
  const max = Math.max(...visible.map((day) => day.quantity));
  visible.forEach((day) => {
    const column = element("div", `day${day.quantity === max ? " peak" : ""}`);
    column.title = `${dateLabel(day.date)}: ${number.format(day.quantity)} unidades`;
    column.setAttribute("aria-label", column.title);
    const bar = element("div", "day-bar");
    bar.style.setProperty("--amount", `${(day.quantity / max) * 130}px`);
    column.append(
      element("span", "day-value", number.format(day.quantity)),
      bar,
      element("span", "day-label", dateLabel(day.date).slice(0, 5)),
    );
    container.append(column);
  });
  $(".trend-card .card-note").textContent =
    days.length > 14
      ? "Últimas 14 datas com registros. O Excel contém o lote completo."
      : "Cada barra representa uma data com registros de perda.";
}

function renderRecords() {
  if (!state.summary) return;
  const query = $("#search").value.trim().toLocaleLowerCase("pt-BR");
  const records = state.summary.records.filter((row) =>
    [row.id, row.produto, row.descricao, row.ordem, row.motivo]
      .join(" ")
      .toLocaleLowerCase("pt-BR")
      .includes(query),
  );
  const pages = Math.max(1, Math.ceil(records.length / pageSize));
  state.page = Math.min(state.page, pages - 1);
  $("#table-count").textContent = `${number.format(records.length)} registros`;
  $("#pagination").textContent = `${state.page + 1} / ${pages}`;
  $("#previous").disabled = state.page === 0;
  $("#next").disabled = state.page + 1 >= pages;
  const body = $("#records");
  body.replaceChildren();
  for (const row of records.slice(
    state.page * pageSize,
    (state.page + 1) * pageSize,
  )) {
    const tr = element("tr");
    const product = element("td", "", row.descricao);
    product.append(element("small", "", `${row.produto} / ${row.ordem}`));
    const line = element("td");
    line.append(element("span", "tag", row.linha));
    tr.append(
      element("td", "", dateLabel(row.data)),
      product,
      line,
      element("td", "", row.motivo),
      element("td", "numeric", number.format(row.quantidade)),
      element("td", "numeric", currency.format(row.custo_centavos / 100)),
    );
    body.append(tr);
  }
  if (!records.length) {
    const tr = element("tr");
    const td = element("td", "empty", "Nenhum registro corresponde à busca.");
    td.colSpan = 6;
    tr.append(td);
    body.append(tr);
  }
}

async function loadHistory() {
  const container = $("#history");
  container.replaceChildren(element("p", "empty", "Consultando execuções…"));
  try {
    const data = await api("/api/runs");
    container.replaceChildren();
    if (!data.runs.length)
      container.append(
        element(
          "p",
          "empty",
          "Ainda não há processamentos. Use a demonstração ou importe um lote para começar.",
        ),
      );
    for (const run of data.runs) {
      const row = element("div", "history-row");
      const meta = element("div", "history-meta");
      meta.append(
        element(
          "strong",
          "",
          run.source === "demo" ? "Lote demonstrativo" : "Lote importado",
        ),
        element("small", "", `${run.id.slice(0, 8)} · Consolidado`),
      );
      const open = element("button", "button secondary", "Abrir lote ↗");
      open.type = "button";
      open.addEventListener("click", async () => {
        state.run = run.id;
        $("#line-filter").value = "";
        $("#search").value = "";
        try {
          await loadDashboard();
          location.hash = "overview";
        } catch (error) {
          notify(error.message);
        }
      });
      row.append(
        element("span", "history-icon", "✓"),
        meta,
        element("time", "history-date", dateTime(run.created_at)),
        open,
      );
      container.append(row);
    }
  } catch (error) {
    container.replaceChildren(element("p", "empty", error.message));
  }
}

function navigate() {
  const names = {
    overview: "Visão geral",
    batches: "Processamentos",
    method: "Como funciona",
  };
  const page =
    location.hash.slice(1) in names ? location.hash.slice(1) : "overview";
  document.querySelectorAll(".page").forEach((section) => {
    section.hidden = section.id !== page;
  });
  document.querySelectorAll(".nav-link").forEach((link) => {
    link.classList.toggle("active", link.dataset.page === page);
    if (link.dataset.page === page) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  $("#page-name").textContent = names[page];
  document.title = `Lastro — ${names[page]}`;
  if (page === "batches") loadHistory();
  window.scrollTo({ top: 0 });
}

document
  .querySelectorAll(".run-demo")
  .forEach((button) =>
    button.addEventListener("click", () => processBatch("/api/runs/demo")),
  );
$("#upload-form").addEventListener("submit", (event) => {
  event.preventDefault();
  processBatch("/api/runs", { body: new FormData(event.currentTarget) });
});
document.querySelectorAll(".file-zone input").forEach((input) =>
  input.addEventListener("change", () => {
    input
      .closest(".file-zone")
      .classList.toggle("selected", input.files.length > 0);
    input.nextElementSibling.textContent =
      input.files[0]?.name || "Selecionar arquivo ↗";
  }),
);
$("#line-filter").addEventListener("change", () =>
  loadDashboard().catch((error) => notify(error.message)),
);
$("#search").addEventListener("input", () => {
  state.page = 0;
  renderRecords();
});
$("#previous").addEventListener("click", () => {
  state.page--;
  renderRecords();
});
$("#next").addEventListener("click", () => {
  state.page++;
  renderRecords();
});
$("#refresh-history").addEventListener("click", loadHistory);
window.addEventListener("hashchange", navigate);
navigate();
loadDashboard().catch((error) => notify(error.message));
