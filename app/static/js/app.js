// Jev Decision Engine Workbench — vanilla JS front end.
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = (p) => `${(p * 100).toFixed(1)}%`;
const titleCase = (s) => String(s).replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

// ---------------------------------------------------------------- API + header state

async function api(path, body) {
  const started = performance.now();
  const res = await fetch(path, {
    method: body ? "POST" : "GET",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  const roundTrip = performance.now() - started;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = data.detail;
    const msg = typeof detail === "string" ? detail : detail?.message || JSON.stringify(detail ?? data);
    throw new Error(`${res.status}: ${msg}`);
  }
  if (body) setLatency(roundTrip, data.latency_ms);
  return data;
}

function setLatency(roundTrip, engineMs) {
  const engine = typeof engineMs === "number" ? ` · engine ${engineMs.toFixed(1)}ms` : "";
  $("#latency").textContent = `${roundTrip.toFixed(0)}ms${engine}`;
}

async function loadHealth() {
  try {
    const h = await api("/api/v1/health");
    const badge = $("#mode-badge");
    badge.textContent = h.mock_mode ? "Mock Mode" : "Live API";
    badge.className = `badge ${h.mock_mode ? "bg-amber-500/15 text-amber-300 border border-amber-500/40" : "bg-emerald-500/15 text-emerald-300 border border-emerald-500/40"}`;
    $("#model-badge").textContent = h.model;
    $("#setup-banner").classList.toggle("hidden", h.mock_reason !== "placeholder_credentials");
  } catch (e) {
    $("#mode-badge").textContent = "Offline";
    $("#mode-badge").className = "badge bg-red-500/15 text-red-300 border border-red-500/40";
  }
}

// ---------------------------------------------------------------- shared renderers


function meters(distribution, highlight) {
  const entries = Object.entries(distribution).sort((a, b) => b[1] - a[1]);
  return `<div class="space-y-2">${entries
    .map(([label, p], i) => `
      <div>
        <div class="flex justify-between text-xs mb-1">
          <span class="${label === highlight ? "text-slate-100 font-semibold" : "text-slate-400"}">${esc(titleCase(label))}</span>
          <span class="font-mono text-slate-300">${pct(p)}</span>
        </div>
        <div class="meter"><span class="${label === highlight ? "bg-sky-400" : "bg-slate-500"}" style="width:${(p * 100).toFixed(1)}%"></span></div>
      </div>`)
    .join("")}</div>`;
}

function gauge(distribution, activeIndex, colors) {
  const labels = Object.keys(distribution);
  return `<div class="gauge" style="--levels:${labels.length}">${labels
    .map((l, i) => `<div class="${i <= activeIndex ? colors[i] : ""}" title="${esc(l)}: ${pct(distribution[l])}"></div>`)
    .join("")}</div>
    <div class="grid text-[11px] text-slate-500 mt-1" style="grid-template-columns:repeat(${labels.length},1fr)">${labels
      .map((l) => `<span>${esc(l)}<br><span class="font-mono">${pct(distribution[l])}</span></span>`)
      .join("")}</div>`;
}

function statusTag(escalate, reasons, severe = false, autoText = "Automated Action", escText = "Escalated to Human") {
  const cls = escalate ? `status-escalate${severe ? " severe" : ""}` : "status-auto";
  const list = escalate && reasons?.length
    ? `<ul class="mt-2 text-xs text-slate-400 list-disc list-inside">${reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>`
    : "";
  return `<div><span class="badge ${cls} text-sm px-3 py-1">${escalate ? "⚠ " + escText : "✓ " + autoText}</span>${list}</div>`;
}

function stat(label, value, sub = "") {
  return `<div class="rounded-lg bg-slate-950 border border-slate-800 p-3">
    <div class="label mb-1">${esc(label)}</div>
    <div class="text-xl font-semibold font-mono">${value}</div>
    ${sub ? `<div class="text-xs text-slate-500 mt-0.5">${sub}</div>` : ""}
  </div>`;
}

function footer(d) {
  const cost = d.usage?.cost != null ? ` · $${d.usage.cost.toFixed(6)}` : "";
  return `<details class="mt-5 text-xs text-slate-500">
    <summary class="cursor-pointer hover:text-slate-300">Raw answers · ${esc(d.model)} · ${d.mock_mode ? "mock" : "live"} · ${d.latency_ms.toFixed(1)}ms${cost}</summary>
    <pre class="mt-2 p-3 bg-slate-950 rounded-lg overflow-x-auto text-slate-300">${esc(JSON.stringify(d.answers, null, 2))}</pre>
  </details>`;
}

function showError(target, err) {
  target.innerHTML = `<div class="text-sm text-red-300 bg-red-500/10 border border-red-500/30 rounded-lg p-3">${esc(err.message)}</div>`;
}

async function submitWith(form, target, run) {
  const btn = $("button[type=submit]", form);
  btn.disabled = true;
  target.classList.add("opacity-60");
  try {
    await run();
  } catch (err) {
    showError(target, err);
  } finally {
    btn.disabled = false;
    target.classList.remove("opacity-60");
  }
}

// ---------------------------------------------------------------- tabs

$$(".tab").forEach((tab) =>
  tab.addEventListener("click", () => {
    $$(".tab").forEach((t) => t.classList.toggle("active", t === tab));
    $$(".panel").forEach((p) => p.classList.toggle("hidden", p.id !== `tab-${tab.dataset.tab}`));
  })
);

// ---------------------------------------------------------------- Tab 1: triage

const TRIAGE_PRESETS = {
  "Clear Billing Dispute": {
    subject: "Charged twice for my March invoice",
    text: "Hi, my credit card was charged twice for the Pro subscription invoice #4821 on March 3rd. Both payments of $49 show on my statement. Please refund the duplicate charge to the same card.",
    tier: "pro", channel: "email",
  },
  "Cryptic 3-Word Crash Report": { subject: "", text: "app crashed again", tier: "free", channel: "chat" },
  "Urgent Security Breach": {
    subject: "Account compromised — unknown logins",
    text: "Someone hacked our admin account. We are seeing suspicious logins from another country, our password reset emails are not arriving, and 2FA was disabled without us. The account is compromised, please lock it now.",
    tier: "enterprise", channel: "phone",
  },
  "Feature Request": {
    subject: "Dark mode and Slack integration",
    text: "Would love a dark mode option for the dashboard, and a Slack integration so the team gets notified of new reports. Great product otherwise!",
    tier: "pro", channel: "email",
  },
};

const presetSelect = $("#triage-preset");
presetSelect.innerHTML = Object.keys(TRIAGE_PRESETS).map((k) => `<option>${esc(k)}</option>`).join("") + `<option value="">Custom…</option>`;
function applyPreset() {
  const p = TRIAGE_PRESETS[presetSelect.value];
  if (!p) return;
  $("#triage-subject").value = p.subject;
  $("#triage-text").value = p.text;
  $("#triage-tier").value = p.tier;
  $("#triage-channel").value = p.channel;
}
presetSelect.addEventListener("change", applyPreset);
applyPreset();

const URGENCY_COLORS = ["bg-emerald-400", "bg-yellow-400", "bg-orange-400", "bg-red-500"];
const CATEGORY_STYLE = {
  billing: "bg-sky-500/15 text-sky-300 border border-sky-500/40",
  technical: "bg-violet-500/15 text-violet-300 border border-violet-500/40",
  security: "bg-red-500/15 text-red-300 border border-red-500/40",
  feature: "bg-teal-500/15 text-teal-300 border border-teal-500/40",
};

$("#triage-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const target = $("#triage-result");
  submitWith(e.target, target, async () => {
    const d = await api("/api/v1/triage", {
      text: $("#triage-text").value,
      subject: $("#triage-subject").value || null,
      customer_tier: $("#triage-tier").value || null,
      channel: $("#triage-channel").value || null,
    });
    const severe = d.urgency.level >= 3;
    target.innerHTML = `
      <div class="flex flex-wrap items-start justify-between gap-3 mb-5">
        <div>
          <div class="label">Category</div>
          <span class="badge ${CATEGORY_STYLE[d.category] || "bg-slate-800"} text-base px-3 py-1">${esc(titleCase(d.category))}</span>
        </div>
        ${statusTag(d.requires_human_escalation, d.escalation_reasons, severe)}
      </div>
      <div class="grid grid-cols-2 gap-3 mb-5">
        ${stat("Category confidence", pct(d.confidence), "gate ≥ 70%")}
        ${stat("Ambiguity", pct(d.ambiguity_probability), "gate ≤ 40%")}
      </div>
      <div class="label">Candidate probabilities</div>
      ${meters(d.distribution, d.category)}
      <div class="mt-5">
        <div class="flex justify-between items-baseline"><span class="label">Urgency</span>
          <span class="font-mono text-sm">${esc(d.urgency.label)} <span class="text-slate-500">(${pct(d.urgency.confidence)})</span></span></div>
        ${gauge(d.urgency.distribution, d.urgency.level, URGENCY_COLORS)}
      </div>
      ${footer(d)}`;
  });
});

// ---------------------------------------------------------------- Tab 2: router

const queueTally = {};
function renderQueues() {
  const entries = Object.entries(queueTally).sort((a, b) => b[1] - a[1]);
  const total = entries.reduce((s, [, n]) => s + n, 0);
  $("#route-queues").innerHTML = entries.length
    ? entries.map(([q, n]) => `
        <div>
          <div class="flex justify-between text-xs mb-1"><span class="${q === "human_review" ? "text-amber-300" : "text-slate-300"}">${esc(titleCase(q))}</span><span class="font-mono text-slate-400">${n}</span></div>
          <div class="meter"><span class="${q === "human_review" ? "bg-amber-400" : "bg-sky-400"}" style="width:${(n / total) * 100}%"></span></div>
        </div>`).join("")
    : `<p class="empty">No tasks dispatched yet.</p>`;
}
renderQueues();
$("#route-reset").addEventListener("click", () => { for (const k in queueTally) delete queueTally[k]; renderQueues(); });

const SIZE_COLORS = ["bg-teal-400", "bg-sky-400", "bg-violet-400", "bg-pink-400"];

$("#route-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const target = $("#route-result");
  submitWith(e.target, target, async () => {
    const d = await api("/api/v1/route", {
      title: $("#route-title").value,
      description: $("#route-desc").value,
      requester: $("#route-requester").value || null,
      deadline: $("#route-deadline").value || null,
    });
    queueTally[d.queue] = (queueTally[d.queue] || 0) + 1;
    renderQueues();
    target.innerHTML = `
      <div class="flex flex-wrap items-start justify-between gap-3 mb-5">
        <div>
          <div class="label">Dispatched to</div>
          <div class="text-2xl font-semibold ${d.requires_human_escalation ? "text-amber-300" : "text-sky-300"}">${esc(titleCase(d.queue))}</div>
          ${d.requires_human_escalation ? `<div class="text-xs text-slate-400 mt-1">Suggested queue: ${esc(titleCase(d.suggested_queue))}</div>` : ""}
        </div>
        ${statusTag(d.requires_human_escalation, d.escalation_reasons, false, "Auto-dispatched", "Human Review")}
      </div>
      <div class="grid grid-cols-2 gap-3 mb-5">
        ${stat("Queue confidence", pct(d.confidence), "gate ≥ 65%")}
        ${stat("Needs human judgment", pct(d.human_judgment_probability), "gate ≤ 50%")}
      </div>
      <div class="label">Queue probabilities</div>
      ${meters(d.distribution, d.suggested_queue)}
      <div class="mt-5">
        <div class="flex justify-between items-baseline"><span class="label">Complexity</span><span class="font-mono text-sm">${esc(d.complexity.label)}</span></div>
        ${gauge(d.complexity.distribution, d.complexity.level, SIZE_COLORS)}
      </div>
      ${footer(d)}`;
  });
});

// ---------------------------------------------------------------- Tab 3: clipper

$("#clip-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const target = $("#clip-result");
  submitWith(e.target, target, async () => {
    const d = await api("/api/v1/clip", {
      segment: $("#clip-segment").value,
      video_title: $("#clip-title").value || null,
      start: $("#clip-start").value || null,
      end: $("#clip-end").value || null,
    });
    const clip = d.outcome === "clip";
    const stars = [1, 2, 3, 4, 5].map((i) => `<span class="${i <= Math.round(d.hook_score) ? "text-amber-300" : "text-slate-700"}">★</span>`).join("");
    target.innerHTML = `
      <div class="flex flex-wrap items-start justify-between gap-3 mb-5">
        <div>
          <div class="label">Verdict</div>
          <span class="badge ${clip ? "status-auto" : "bg-slate-800 text-slate-300 border border-slate-700"} text-base px-3 py-1">${clip ? "✂ Clip it" : "Skip"}</span>
        </div>
        ${d.requires_human_escalation ? statusTag(true, d.escalation_reasons, false, "", "Editor Review") : ""}
      </div>
      <div class="grid grid-cols-2 gap-3 mb-5">
        ${stat("Standalone coherence", pct(d.standalone_probability), "clip ≥ 60%")}
        ${stat("Hook score", `${d.hook_score.toFixed(2)}<span class="text-sm text-slate-500"> / 5</span>`, `<span class="text-base tracking-widest">${stars}</span>`)}
      </div>
      <div class="label">Coherence</div>
      <div class="meter mb-5"><span class="${d.standalone_probability >= 0.6 ? "bg-emerald-400" : "bg-amber-400"}" style="width:${(d.standalone_probability * 100).toFixed(1)}%"></span></div>
      <div class="label">Hook distribution (1–5)</div>
      ${gauge(d.hook_distribution, Math.round(d.hook_score) - 1, ["bg-slate-500", "bg-sky-500", "bg-sky-400", "bg-amber-400", "bg-amber-300"])}
      ${footer(d)}`;
  });
});

// ---------------------------------------------------------------- Tab 4: playground

const QUESTION_DEFAULTS = {
  choice: {
    key: "sentiment", instructions: "What is the customer's overall sentiment?",
    criteria: "positive: Happy, praising, satisfied\nnegative: Frustrated, angry, disappointed\nmixed: Both praise and complaints",
    hint: "One option per line: label: guidance",
  },
  score: {
    key: "severity", instructions: "How severe is the reported problem?",
    criteria: "Cosmetic, no impact\nAnnoying but has a workaround\nBlocks a key workflow\nData loss or outage",
    hint: "One level per line, lowest first",
  },
  noul: {
    key: "is_bug", instructions: "Does the message report a software bug?",
    criteria: "true: Describes an error, failure, timeout, or broken behavior\nfalse: Praise, a question, or a feature idea only",
    hint: "Two lines: true: … and false: …",
  },
};
const TYPE_STYLE = { choice: "bg-sky-500/15 text-sky-300", score: "bg-violet-500/15 text-violet-300", noul: "bg-teal-500/15 text-teal-300" };

function addQuestion(type) {
  const d = QUESTION_DEFAULTS[type];
  const node = $("#tpl-question").content.firstElementChild.cloneNode(true);
  node.dataset.type = type;
  $(".q-type", node).textContent = titleCase(type);
  $(".q-type", node).classList.add(...TYPE_STYLE[type].split(" "));
  const used = $$(".q-key").map((i) => i.value);
  let key = d.key, n = 2;
  while (used.includes(key)) key = `${d.key}_${n++}`;
  $(".q-key", node).value = key;
  $(".q-instructions", node).value = d.instructions;
  $(".q-criteria", node).value = d.criteria;
  $(".q-hint", node).textContent = d.hint;
  $(".q-remove", node).addEventListener("click", () => node.remove());
  $("#custom-questions").appendChild(node);
}
$$("[data-add]").forEach((b) => b.addEventListener("click", () => addQuestion(b.dataset.add)));
["choice", "score", "noul"].forEach(addQuestion);

const threshold = $("#custom-threshold");
threshold.addEventListener("input", () => ($("#custom-threshold-val").textContent = Number(threshold.value).toFixed(2)));

function parsePairs(text) {
  const out = {};
  text.split("\n").map((l) => l.trim()).filter(Boolean).forEach((line) => {
    const i = line.indexOf(":");
    if (i === -1) out[line] = null;
    else out[line.slice(0, i).trim()] = line.slice(i + 1).trim() || null;
  });
  return out;
}

function collectQuestions() {
  const questions = {};
  for (const node of $$(".question")) {
    const type = node.dataset.type;
    const key = $(".q-key", node).value.trim();
    if (!key) throw new Error("Every question needs a key.");
    if (questions[key]) throw new Error(`Duplicate question key "${key}".`);
    const instructions = $(".q-instructions", node).value.trim() || key;
    const raw = $(".q-criteria", node).value;
    let criteria;
    if (type === "score") criteria = raw.split("\n").map((l) => l.trim()).filter(Boolean);
    else if (type === "noul") {
      const pairs = parsePairs(raw);
      criteria = { true: pairs.true || "Yes", false: pairs.false || "No" };
    } else criteria = parsePairs(raw);
    questions[key] = { type, instructions, criteria };
  }
  if (!Object.keys(questions).length) throw new Error("Add at least one question.");
  return questions;
}

function renderAnswer(key, a) {
  if (a.type === "choice")
    return `<div class="label">${esc(key)} · choice → <span class="text-sky-300 normal-case">${esc(a.choice)}</span> <span class="font-mono normal-case">(${pct(a.confidence)})</span></div>${meters(a.probabilities, a.choice)}`;
  if (a.type === "score") {
    const legend = a.legend || {};
    const dist = Object.fromEntries(Object.entries(a.probabilities).map(([lvl, p]) => [`${lvl}`, p]));
    const top = Number(Object.entries(a.probabilities).sort((x, y) => y[1] - x[1])[0][0]);
    return `<div class="label">${esc(key)} · score → <span class="text-violet-300 normal-case font-mono">${a.score.toFixed(2)}</span> <span class="font-mono normal-case">(${pct(a.confidence)})</span></div>
      ${gauge(dist, top, ["bg-violet-300", "bg-violet-400", "bg-violet-500", "bg-violet-600", "bg-violet-700", "bg-violet-800"].slice(0, Object.keys(dist).length))}
      <p class="text-xs text-slate-500 mt-1">Most likely: ${esc(typeof legend[top] === "string" ? legend[top] : `level ${top}`)}</p>`;
  }
  return `<div class="label">${esc(key)} · noul → <span class="text-teal-300 normal-case font-mono">P(true) = ${pct(a.noul)}</span></div>
    <div class="meter"><span class="bg-teal-400" style="width:${(a.noul * 100).toFixed(1)}%"></span></div>`;
}

$("#custom-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const target = $("#custom-result");
  submitWith(e.target, target, async () => {
    const d = await api("/api/v1/decide", {
      state: $("#custom-state").value,
      questions: collectQuestions(),
      confidence_threshold: Number(threshold.value),
    });
    target.innerHTML = `
      <div class="mb-5">${statusTag(d.requires_human_escalation, d.escalation_reasons, false, "All answers confident", "Needs Human Review")}</div>
      <div class="space-y-5">${Object.entries(d.answers).map(([k, a]) => `<div>${renderAnswer(k, a)}</div>`).join("")}</div>
      ${footer(d)}`;
  });
});

loadHealth();
