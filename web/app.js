"use strict";

const $ = (id) => document.getElementById(id);
const state = { overview: null, series: [], activeSeries: null, range: "5", observations: [], request: 0, charts: new Map() };
const SVG_NS = "http://www.w3.org/2000/svg";
const MONTH = new Intl.DateTimeFormat("en-GB", { month: "short", year: "numeric", timeZone: "UTC" });
const LONG_MONTH = new Intl.DateTimeFormat("en-GB", { month: "long", year: "numeric", timeZone: "UTC" });
const NUMBER = new Intl.NumberFormat("en-GB", { maximumFractionDigits: 2 });

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined && text !== null) element.textContent = String(text);
  return element;
}

function svgNode(tag, attributes = {}, text) {
  const element = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, String(value));
  if (text !== undefined) element.textContent = text;
  return element;
}

function number(value, decimals) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "—";
  return decimals === undefined ? NUMBER.format(Number(value)) : Number(value).toFixed(decimals);
}

function parseDate(value) {
  if (!value) return null;
  const date = new Date(String(value).length === 7 ? `${value}-01T00:00:00Z` : value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function month(value, long = false) {
  const date = parseDate(value);
  return date ? (long ? LONG_MONTH : MONTH).format(date) : "Date unavailable";
}

function safeUrl(url) {
  if (typeof url !== "string" || !url.trim()) return null;
  try {
    const parsed = new URL(url, window.location.origin);
    return ["https:", "http:"].includes(parsed.protocol) ? parsed.href : null;
  } catch { return null; }
}

function externalLink(label, url, className) {
  const href = safeUrl(url);
  const element = node(href ? "a" : "span", className, label);
  if (href) {
    element.href = href;
    element.target = "_blank";
    element.rel = "noopener noreferrer";
  }
  return element;
}

async function api(path, options = {}) {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), options.method === "POST" ? 65000 : 30000);
  try {
    const response = await fetch(path, { ...options, signal: controller.signal, headers: { Accept: "application/json", ...options.headers } });
    if (!response.ok) {
      if (response.status === 429) throw new Error("The research desk is receiving too many requests. Please wait a moment and try again.");
      if (response.status === 503) throw new Error("The service is warming up or temporarily unavailable. Please try again shortly.");
      if (response.status === 422) throw new Error("Please enter a question of 8–600 characters and try again.");
      throw new Error(`The request could not be completed (HTTP ${response.status}). Please try again.`);
    }
    return await response.json();
  } catch (error) {
    if (error.name === "AbortError") throw new Error("This request took too long. Please try again in a moment.");
    if (error instanceof TypeError) throw new Error("We couldn’t reach the service. Check your connection and try again.");
    throw error;
  } finally { window.clearTimeout(timeout); }
}

function setView() {
  const requested = window.location.hash.slice(1) || "overview";
  const active = ["overview", "forecast", "evidence", "methodology"].includes(requested) ? requested : "overview";
  document.querySelectorAll(".view").forEach((section) => { section.hidden = section.id !== `view-${active}`; });
  document.querySelectorAll(".nav-link").forEach((link) => {
    const selected = link.dataset.view === active;
    link.classList.toggle("active", selected);
    if (selected) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  const labels = { overview: "Overview", forecast: "Forecast lab", evidence: "Ask evidence", methodology: "Methodology" };
  $("page-crumb").textContent = labels[active];
  document.title = `${labels[active]} · Open Finance Intelligence`;
  for (const [id, config] of state.charts) {
    if ($(id).offsetWidth) drawChart(id, config);
  }
}

function sourceName(source) {
  if (typeof source === "string") {
    if (/bank of england/i.test(source)) return "Bank of England";
    if (/national statistics|\bons\b/i.test(source)) return "ONS";
    if (/financial conduct|\bfca\b/i.test(source)) return "FCA";
    return source;
  }
  return "Official source";
}

function shortUnit(unit) {
  const value = String(unit || "");
  return /percent|%/i.test(value) ? "%" : value;
}

function indicatorName(name) {
  if (/Bank Rate/i.test(String(name))) return "Bank Rate · monthly avg.";
  return String(name || "Economic indicator")
    .replace(/^UK\s+/i, "")
    .replace(/ \(.*?\)/g, "")
    .replace(/Consumer Prices Index/i, "CPI inflation")
    .replace(/Consumer Price Index/i, "CPI inflation");
}

function renderIndicators(series) {
  const grid = $("indicator-grid");
  grid.replaceChildren();
  grid.setAttribute("aria-busy", "false");
  for (const item of series) {
    const card = node("button", "indicator-card");
    card.type = "button";
    card.dataset.series = item.id;
    if (item.description) card.title = item.description;
    card.setAttribute("aria-pressed", String(item.id === state.activeSeries));
    card.setAttribute("aria-label", `${item.name}: ${number(item.latest_value)} ${item.unit || ""}, ${month(item.latest_date)}. Show history.`);
    card.classList.toggle("active", item.id === state.activeSeries);
    const heading = node("div", "indicator-heading");
    heading.append(node("span", "", indicatorName(item.name)), node("span", "", "↗"));
    const isMillions = item.unit === "£ million";
    const value = node("div", "indicator-value", isMillions ? `£${number(item.latest_value / 1000000, 2)}` : number(item.latest_value));
    value.append(node("small", "", isMillions ? "trillion" : shortUnit(item.unit)));
    const meta = node("div", "indicator-meta");
    const period = item.id === "unemployment" && item.latest_period_label ? item.latest_period_label.replace(/^(\d{4})\s+(.+)$/, "$2 $1").replace(/[A-Z]+/g, (text) => text.charAt(0) + text.slice(1).toLowerCase()) : month(item.latest_date);
    meta.append(node("span", "", period), node("span", "meta-source", sourceName(item.source)));
    card.append(heading, value, meta);
    card.addEventListener("click", () => selectSeries(item.id));
    grid.append(card);
  }
  if (!series.length) grid.append(node("p", "muted", "No economic indicators are available in this snapshot."));
  const select = $("series-select");
  select.replaceChildren();
  for (const item of series) {
    const option = node("option", "", item.name);
    option.value = item.id;
    select.append(option);
  }
  select.disabled = !series.length;
  if (state.activeSeries) select.value = state.activeSeries;
}

async function selectSeries(id) {
  const metadata = state.series.find((item) => item.id === id);
  if (!metadata) return;
  state.activeSeries = id;
  state.observations = [];
  state.charts.delete("history-chart");
  $("series-select").value = id;
  document.querySelectorAll(".indicator-card").forEach((card) => {
    const selected = card.dataset.series === id;
    card.classList.toggle("active", selected);
    card.setAttribute("aria-pressed", String(selected));
  });
  $("chart-unit").textContent = metadata.unit || "";
  $("history-chart").replaceChildren(node("div", "chart-loading", "Loading observations…"));
  $("history-table").replaceChildren();
  $("chart-period").textContent = "Loading observations";
  $("chart-source").hidden = true;
  const requestId = ++state.request;
  try {
    const data = await api(`/api/data/${encodeURIComponent(id)}`);
    if (requestId !== state.request) return;
    state.observations = (data.observations || []).filter((item) => parseDate(item.date) && item.value !== null && Number.isFinite(Number(item.value))).sort((a, b) => parseDate(a.date) - parseDate(b.date));
    renderHistory();
    const url = safeUrl(data.series?.source_url || metadata.source_url);
    if (url) { $("chart-source").href = url; $("chart-source").hidden = false; }
  } catch (error) {
    if (requestId !== state.request) return;
    state.charts.delete("history-chart");
    const empty = node("div", "chart-empty");
    const wrapper = node("div");
    wrapper.append(node("p", "", error.message));
    const retry = node("button", "button button-outline", "Retry this series ↻");
    retry.addEventListener("click", () => selectSeries(id));
    wrapper.append(retry);
    empty.append(wrapper);
    $("history-chart").replaceChildren(empty);
    $("chart-period").textContent = "Observations unavailable";
  }
}

function renderHistory() {
  const metadata = state.series.find((item) => item.id === state.activeSeries);
  if (!metadata) return;
  let observations = state.observations;
  if (state.range !== "all" && observations.length) {
    const cutoff = parseDate(observations[observations.length - 1].date);
    cutoff.setUTCFullYear(cutoff.getUTCFullYear() - Number(state.range));
    observations = observations.filter((item) => parseDate(item.date) >= cutoff);
  }
  const isMillions = metadata.unit === "£ million";
  const chartRows = isMillions ? observations.map((row) => ({ ...row, value: row.value / 1000000 })) : observations;
  const chartUnit = isMillions ? "£ trillion" : metadata.unit;
  $("chart-unit").textContent = chartUnit || "";
  const config = { title: `${metadata.name} over time`, rows: chartRows, lines: [{ key: "value", label: metadata.name, color: "#087e78", fill: true }], unit: chartUnit, height: 255 };
  state.charts.set("history-chart", config);
  drawChart("history-chart", config);
  $("chart-period").textContent = observations.length ? `${month(observations[0].date)} — ${month(observations[observations.length - 1].date)} · ${observations.length} observations` : "No observations in this period";
  $("data-value-heading").textContent = metadata.unit ? `Value (${metadata.unit})` : "Value";
  renderTable("history-table", observations.slice().reverse(), ["date", "value"]);
}

function renderTable(id, rows, fields) {
  const body = $(id);
  body.replaceChildren();
  if (!rows.length) {
    const row = node("tr");
    const cell = node("td", "", "No observations available.");
    cell.colSpan = fields.length;
    row.append(cell);
    body.append(row);
    return;
  }
  const fragment = document.createDocumentFragment();
  for (const item of rows) {
    const row = node("tr");
    for (const field of fields) row.append(node("td", "", field === "date" ? month(item[field]) : number(item[field], 2)));
    fragment.append(row);
  }
  body.append(fragment);
}

function drawChart(id, config) {
  const container = $(id);
  if (!container.offsetWidth) return;
  const { rows, lines, unit = "", title, height = 255 } = config;
  container.replaceChildren();
  if (!rows.length) { container.append(node("div", "chart-empty", "No observations are available for this view.")); return; }
  const width = Math.max(container.clientWidth, 240);
  const mobile = width < 400;
  const chartHeight = mobile ? Math.max(height - 25, 205) : height;
  const margin = { left: mobile ? 33 : 39, right: 14, top: 15, bottom: 35 };
  const innerWidth = width - margin.left - margin.right;
  const innerHeight = chartHeight - margin.top - margin.bottom;
  const dates = rows.map((row) => parseDate(row.date).getTime());
  const finiteValues = rows.flatMap((row) => lines.map((line) => Number(row[line.key]))).filter(Number.isFinite);
  const band = rows.every((row) => Number.isFinite(row.lower) && Number.isFinite(row.upper));
  if (band) finiteValues.push(...rows.flatMap((row) => [row.lower, row.upper]));
  if (!finiteValues.length) { container.append(node("div", "chart-empty", "No numeric values are available.")); return; }
  let minimum = Math.min(...finiteValues);
  let maximum = Math.max(...finiteValues);
  const pad = (maximum - minimum || Math.abs(maximum) || 1) * .12;
  minimum -= pad;
  maximum += pad;
  const firstDate = dates[0];
  const lastDate = dates[dates.length - 1];
  const x = (date) => margin.left + (date - firstDate) / (lastDate - firstDate || 1) * innerWidth;
  const y = (value) => margin.top + (maximum - value) / (maximum - minimum) * innerHeight;
  const svg = svgNode("svg", { viewBox: `0 0 ${width} ${chartHeight}`, role: "img", "aria-labelledby": `${id}-title ${id}-description` });
  svg.append(svgNode("title", { id: `${id}-title` }, title));
  svg.append(svgNode("desc", { id: `${id}-description` }, `${rows.length} observations, ${month(rows[0].date)} to ${month(rows[rows.length - 1].date)}. Values in ${unit || "the indicated units"}. A data table follows this chart.`));
  const defs = svgNode("defs");
  const gradient = svgNode("linearGradient", { id: `${id}-fill`, x1: "0", y1: "0", x2: "0", y2: "1" });
  gradient.append(svgNode("stop", { offset: "0%", "stop-color": "#087e78", "stop-opacity": ".12" }), svgNode("stop", { offset: "100%", "stop-color": "#087e78", "stop-opacity": ".005" }));
  defs.append(gradient);
  svg.append(defs);
  for (let index = 0; index <= 4; index += 1) {
    const value = minimum + (maximum - minimum) * index / 4;
    const position = y(value);
    svg.append(svgNode("line", { x1: margin.left, x2: width - margin.right, y1: position, y2: position, stroke: "#e7ebdf", "stroke-width": "1", "stroke-dasharray": "3 4" }));
    svg.append(svgNode("text", { x: margin.left - 10, y: position + 3, "text-anchor": "end", fill: "#92a186", "font-size": 9, "font-family": "Arial, sans-serif" }, number(value, Math.abs(maximum - minimum) > 12 ? 0 : 1)));
  }
  const tickCount = mobile ? 3 : 5;
  const seen = new Set();
  for (let index = 0; index < tickCount; index += 1) {
    const rowIndex = Math.round(index * (rows.length - 1) / (tickCount - 1));
    if (seen.has(rowIndex)) continue;
    seen.add(rowIndex);
    svg.append(svgNode("text", { x: x(dates[rowIndex]), y: chartHeight - 8, "text-anchor": index === 0 ? "start" : index === tickCount - 1 ? "end" : "middle", fill: "#92a186", "font-size": 9, "font-family": "Arial, sans-serif" }, month(rows[rowIndex].date)));
  }
  if (band) {
    const upper = rows.map((row, index) => `${index ? "L" : "M"}${x(dates[index]).toFixed(2)},${y(row.upper).toFixed(2)}`).join(" ");
    const lower = rows.map((row, index) => `L${x(dates[index]).toFixed(2)},${y(row.lower).toFixed(2)}`).reverse().join(" ");
    svg.append(svgNode("path", { d: `${upper} ${lower} Z`, fill: "#c67756", opacity: ".08" }));
  }
  for (const line of lines) {
    const points = rows.map((row, index) => ({ x: x(dates[index]), y: y(Number(row[line.key])) })).filter((point) => Number.isFinite(point.y));
    if (!points.length) continue;
    const path = points.map((point, index) => `${index ? "L" : "M"}${point.x.toFixed(2)},${point.y.toFixed(2)}`).join(" ");
    if (line.fill) svg.append(svgNode("path", { d: `${path} L${points[points.length - 1].x},${chartHeight - margin.bottom} L${points[0].x},${chartHeight - margin.bottom} Z`, fill: `url(#${id}-fill)` }));
    svg.append(svgNode("path", { d: path, fill: "none", stroke: line.color, "stroke-width": 2.25, "stroke-linejoin": "round", "stroke-linecap": "round" }));
    const last = points[points.length - 1];
    svg.append(svgNode("circle", { cx: last.x, cy: last.y, r: 3.3, fill: line.color, stroke: "#fffefa", "stroke-width": 1.8 }));
  }
  const hoverLine = svgNode("line", { x1: 0, x2: 0, y1: margin.top, y2: chartHeight - margin.bottom, stroke: "#9fb399", "stroke-width": 1, "stroke-dasharray": "3 3", visibility: "hidden" });
  svg.append(hoverLine);
  const tooltip = node("div", "chart-tooltip");
  tooltip.hidden = true;
  const overlay = svgNode("rect", { x: margin.left, y: margin.top, width: innerWidth, height: innerHeight, fill: "transparent", "aria-hidden": "true" });
  overlay.addEventListener("pointermove", (event) => {
    const rect = svg.getBoundingClientRect();
    const cursor = (event.clientX - rect.left) * width / rect.width;
    const time = firstDate + (cursor - margin.left) / innerWidth * (lastDate - firstDate);
    let nearest = 0;
    for (let index = 1; index < dates.length; index += 1) if (Math.abs(dates[index] - time) < Math.abs(dates[nearest] - time)) nearest = index;
    hoverLine.setAttribute("x1", x(dates[nearest]));
    hoverLine.setAttribute("x2", x(dates[nearest]));
    hoverLine.setAttribute("visibility", "visible");
    tooltip.replaceChildren(node("span", "", month(rows[nearest].date)));
    for (const line of lines) tooltip.append(node("strong", "", `${lines.length > 1 ? `${line.label}: ` : ""}${number(rows[nearest][line.key], 2)}${shortUnit(unit) === "%" ? "%" : ` ${unit}`}`));
    tooltip.hidden = false;
    tooltip.style.left = `${Math.max(0, Math.min(x(dates[nearest]) + 12, width - tooltip.offsetWidth - 3))}px`;
    tooltip.style.top = "8px";
  });
  overlay.addEventListener("pointerleave", () => { tooltip.hidden = true; hoverLine.setAttribute("visibility", "hidden"); });
  svg.append(overlay);
  container.append(svg, tooltip);
}

function renderForecast(forecast, evaluation) {
  if (!forecast || forecast.value === null || forecast.value === undefined) {
    $("forecast-period").textContent = "No forecast is available";
    $("forecast-range").textContent = "Please try again after the next update.";
    return;
  }
  const suffix = shortUnit(forecast.unit) === "%" ? "%" : ` ${forecast.unit || ""}`;
  $("forecast-period").textContent = `${month(forecast.target_date, true)} · ${forecast.target || "CPI inflation"}`;
  $("forecast-number").replaceChildren(document.createTextNode(number(forecast.value, 2)), node("small", "", suffix.trim()));
  const interval = `${number(forecast.lower, 2)}–${number(forecast.upper, 2)}${suffix} · ${forecast.interval_label || "prediction interval"}`;
  $("forecast-range").textContent = interval;
  $("forecast-last").textContent = `${number(forecast.last_observed_value, 2)}${suffix} · ${month(forecast.last_observed_date)}`;
  $("forecast-model").textContent = forecast.model_name || "Forecast model";
  $("detail-target").textContent = `${month(forecast.target_date, true)} · ${forecast.target || "NEXT-OBSERVATION FORECAST"}`;
  $("detail-value").textContent = `${number(forecast.value, 2)}${suffix}`;
  $("detail-range").textContent = interval;
  $("detail-origin").textContent = `Forecast origin: ${month(forecast.as_of, true)}`;
  $("detail-model").textContent = forecast.model_name || "Forecast model";
  $("detail-caveat").textContent = forecast.caveat || "Model estimates have uncertainty. Inspect the evaluation and methodology before interpreting them.";
  $("model-version").textContent = forecast.model_version ? `Model version ${forecast.model_version}` : "";
  if (!evaluation) return;
  const comparison = evaluation.baseline_comparison;
  $("verdict-title").textContent = comparison ? (comparison.outperforms_baseline_on_test ? "The selected model improves on persistence." : "The simpler baseline was stronger.") : "Read the evidence alongside the estimate.";
  $("verdict-copy").textContent = comparison ? `${evaluation.selected_model} test MAE: ${number(comparison.selected_model_test_mae, 3)} percentage points. ${comparison.baseline} test MAE: ${number(comparison.baseline_test_mae, 3)}. The model was chosen on validation data; these final test results were not used to reselect it.` : evaluation.deployment_assessment || "The final test set is reserved for reporting model performance.";
  const intervalMetrics = evaluation.interval;
  if (intervalMetrics && Number.isFinite(intervalMetrics.test_coverage)) {
    $("coverage-value").textContent = `${number(intervalMetrics.test_coverage * 100, 1)}%`;
    $("coverage-label").textContent = `Actual test coverage for the nominal ${number(intervalMetrics.nominal_coverage * 100, 0)}% interval`;
  }
  if (evaluation.importance_method) $("importance-description").textContent = `${evaluation.importance_method} Association, not causation.`;
  const split = evaluation.split || {};
  $("backtest-period").textContent = split.test_start && split.test_end ? `Final held-out test: ${month(split.test_start)} — ${month(split.test_end)}. Shading shows the available prediction interval.` : "Held-out model predictions alongside observed inflation.";
  const backtest = (evaluation.backtest || []).filter((row) => parseDate(row.date) && Number.isFinite(row.actual) && Number.isFinite(row.predicted)).sort((a, b) => parseDate(a.date) - parseDate(b.date));
  const chart = { title: "Held-out inflation forecasts compared with observed values", rows: backtest, lines: [{ key: "actual", label: "Observed", color: "#087e78" }, { key: "predicted", label: "Predicted", color: "#c67756" }], unit: forecast.unit || "%", height: 290 };
  state.charts.set("backtest-chart", chart);
  drawChart("backtest-chart", chart);
  renderTable("backtest-table", backtest.slice().reverse(), ["date", "actual", "predicted", "lower", "upper"]);
  const metrics = $("metrics-table");
  metrics.replaceChildren();
  for (const metric of evaluation.metrics || []) {
    const row = node("tr");
    const selected = metric.model === evaluation.selected_model;
    const label = node("td", selected ? "selected-model" : "", metric.model);
    if (selected) label.append(node("span", "selected-tag", "Selected model"));
    row.append(label, node("td", "", number(metric.mae, 3)), node("td", "", number(metric.rmse, 3)));
    metrics.append(row);
  }
  if (!(evaluation.metrics || []).length) metrics.append(node("tr", "", "No evaluation metrics available."));
  const importance = $("importance-chart");
  importance.replaceChildren();
  const features = (evaluation.importance || []).filter((item) => Number.isFinite(item.importance)).sort((a, b) => Math.abs(b.importance) - Math.abs(a.importance));
  const maximum = Math.max(...features.map((item) => Math.abs(item.importance)), .000001);
  for (const feature of features) {
    const item = node("div", "importance-item");
    const track = node("div", "importance-track");
    const fill = node("div", `importance-fill${feature.importance < 0 ? " negative" : ""}`);
    fill.style.width = `${Math.abs(feature.importance) / maximum * 100}%`;
    track.append(fill);
    item.append(node("span", "importance-label", feature.feature.replaceAll("_", " ")), track, node("span", "importance-score", number(feature.importance, 3)));
    importance.append(item);
  }
  if (!features.length) importance.append(node("p", "muted", "Feature importance is not available for this model."));
  const caveats = $("evaluation-caveats");
  caveats.replaceChildren();
  for (const caveat of evaluation.caveats || []) caveats.append(node("li", "", caveat));
  const timeline = $("split-timeline");
  timeline.replaceChildren();
  const splits = [["Training", split.train_end ? `Through ${month(split.train_end)}` : "Dates unavailable"], ["Validation", split.validation_start ? `${month(split.validation_start)} — ${month(split.validation_end)}` : "Dates unavailable"], ["Test", split.test_start ? `${month(split.test_start)} — ${month(split.test_end)}` : "Dates unavailable"]];
  for (const [label, dates] of splits) {
    const segment = node("div", "split-segment");
    segment.append(node("strong", "", label), node("span", "", dates));
    timeline.append(segment);
  }
}

function renderCorpus(corpus) {
  $("corpus-count").textContent = `${corpus.length} public source${corpus.length === 1 ? "" : "s"}`;
  const list = $("corpus-list");
  list.replaceChildren();
  for (const document of corpus) {
    const item = node("article", "corpus-item");
    const url = document.url || document.source_url;
    const institution = document.publisher || document.source || (String(url).includes("fca.org.uk") ? "FCA" : String(url).includes("bankofengland.co.uk") ? "Bank of England" : "Public document");
    item.append(node("p", "source-label", institution), externalLink(`${document.title || document.name || "Source document"} ↗`, url), node("div", "source-date", document.published || document.published_date ? `Published ${month(document.published || document.published_date)}` : "Publication date not supplied"));
    list.append(item);
  }
  if (!corpus.length) list.append(node("p", "muted", "The source library is currently unavailable."));
  const sources = $("data-sources");
  sources.replaceChildren();
  for (const series of state.series) sources.append(externalLink(`${sourceName(series.source)} · ${series.name} ↗`, series.source_url));
}

function readableMode(mode) {
  if (!mode) return "Mode not supplied";
  if (/extract/i.test(mode)) return "Extractive evidence · no LLM";
  if (/llm|generat|openai/i.test(mode)) return "Grounded language-model answer";
  if (/abstain/i.test(mode)) return "Evidence threshold not met";
  return String(mode).replaceAll("_", " ");
}

function renderAnswer(result) {
  const panel = $("answer-panel");
  panel.replaceChildren();
  const status = node("div", `answer-status${result.abstained ? " abstained" : ""}`);
  status.append(node("p", "eyebrow", result.abstained ? "NOT ENOUGH EVIDENCE" : "FROM THE SOURCE DOCUMENTS"), node("span", "answer-mode", readableMode(result.mode)));
  panel.append(status, node("div", "answer-text", result.answer || "No supported answer was returned."));
  if (result.reason) panel.append(node("p", "answer-reason", result.reason));
  const meta = node("div", "answer-meta");
  if (Number.isFinite(result.confidence)) meta.append(node("span", "", `Retrieval support: ${number(result.confidence, 3)} · not a probability`));
  if (result.corpus_as_of) meta.append(node("span", "", `Corpus snapshot: ${month(result.corpus_as_of)}`));
  panel.append(meta);
  if (Array.isArray(result.sources) && result.sources.length) {
    panel.append(node("h3", "sources-heading", result.abstained ? "Retrieved passages · not sufficient to answer" : `Supporting evidence · ${result.sources.length} passage${result.sources.length === 1 ? "" : "s"}`));
    result.sources.forEach((source, index) => {
      const item = node("article", "answer-source");
      const title = node("h3");
      title.append(node("span", "source-number", `[${index + 1}]`), externalLink(`${source.title || "Source document"} ↗`, source.url));
      item.append(title);
      if (source.excerpt) item.append(node("blockquote", "", source.excerpt));
      if (source.published) item.append(node("p", "source-date", `Published ${month(source.published, true)}`));
      panel.append(item);
    });
  }
}

async function askQuestion(event) {
  event.preventDefault();
  const input = $("question-input");
  const question = input.value.trim();
  if (question.length < 8 || question.length > 600) { input.setCustomValidity("Please enter a question of 8–600 characters."); input.reportValidity(); return; }
  input.setCustomValidity("");
  const panel = $("answer-panel");
  const button = $("ask-button");
  button.disabled = true;
  button.textContent = "Reading evidence…";
  panel.setAttribute("aria-busy", "true");
  const loading = node("div", "ask-loading");
  loading.append(node("span", "spinner"), node("p", "", "Finding and checking relevant source passages…"));
  panel.replaceChildren(loading);
  try {
    const answer = await api("/api/ask", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question }) });
    renderAnswer(answer);
  } catch (error) {
    const wrapper = node("div", "ask-error");
    wrapper.append(node("strong", "", "We couldn’t retrieve an answer."), node("p", "", error.message));
    const retry = node("button", "button button-outline", "Try this question again ↻");
    retry.addEventListener("click", () => $("ask-form").requestSubmit());
    wrapper.append(retry);
    panel.replaceChildren(wrapper);
  } finally {
    button.disabled = false;
    button.replaceChildren(document.createTextNode("Find evidence "), node("span", "", "↗"));
    panel.setAttribute("aria-busy", "false");
  }
}

async function healthCheck() {
  const status = $("api-status");
  try {
    await api("/health");
    status.className = "status healthy";
    status.lastElementChild.textContent = "Service online";
  } catch {
    status.className = "status unhealthy";
    status.lastElementChild.textContent = "Service unavailable";
  }
}

async function loadOverview() {
  $("app-error").hidden = true;
  $("retry-app").disabled = true;
  try {
    const data = await api("/api/overview");
    state.overview = data;
    state.series = Array.isArray(data.series) ? data.series : [];
    state.activeSeries = state.series.find((item) => /inflation|cpi/i.test(`${item.id} ${item.name}`))?.id || state.series[0]?.id;
    renderIndicators(state.series);
    renderForecast(data.forecast, data.evaluation);
    renderCorpus(Array.isArray(data.corpus) ? data.corpus : []);
    if (state.activeSeries) await selectSeries(state.activeSeries);
  } catch (error) {
    $("app-error-message").textContent = error.message;
    $("app-error").hidden = false;
    $("indicator-grid").setAttribute("aria-busy", "false");
    $("indicator-grid").replaceChildren();
    $("history-chart").replaceChildren(node("div", "chart-empty", "The data snapshot is unavailable. Use Try again above to reconnect."));
    $("forecast-period").textContent = "Forecast unavailable";
    $("forecast-range").textContent = "Reconnect to load the latest snapshot.";
  } finally { $("retry-app").disabled = false; }
}

window.addEventListener("hashchange", () => { setView(); window.scrollTo({ top: 0, behavior: "instant" }); });
$("series-select").addEventListener("change", (event) => selectSeries(event.target.value));
$("range-tabs").querySelectorAll("button").forEach((button) => button.addEventListener("click", () => {
  state.range = button.dataset.range;
  $("range-tabs").querySelectorAll("button").forEach((item) => { item.classList.toggle("selected", item === button); item.setAttribute("aria-pressed", String(item === button)); });
  renderHistory();
}));
$("ask-form").addEventListener("submit", askQuestion);
$("question-input").addEventListener("input", () => $("question-input").setCustomValidity(""));
document.querySelectorAll("[data-question]").forEach((button) => button.addEventListener("click", () => {
  $("question-input").value = button.dataset.question;
  $("question-input").focus();
  if (!$("ask-button").disabled) $("ask-form").requestSubmit();
}));
$("retry-app").addEventListener("click", () => { loadOverview(); healthCheck(); });
let resizeTimer;
window.addEventListener("resize", () => {
  window.clearTimeout(resizeTimer);
  resizeTimer = window.setTimeout(() => { for (const [id, config] of state.charts) if ($(id).offsetWidth) drawChart(id, config); }, 120);
});
setView();
loadOverview();
healthCheck();
