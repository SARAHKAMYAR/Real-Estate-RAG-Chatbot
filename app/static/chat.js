import { boundedHistory, safeUrl, errorMessage } from "/static/history.mjs";

const log = document.getElementById("log"), form = document.getElementById("form"),
      input = document.getElementById("input"), send = document.getElementById("send");
let history = [];
let messageId = 0;

const esc = s => s.replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));

function renderAnswer(text, id) {
  const inline = s => esc(s)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\[(\d+(?:\s*,\s*\d+)*)\]/g, (_, refs) => refs.split(",").map(r =>
      `<button class="cite" data-target="${id}-${r.trim()}" title="Show source ${r.trim()}">${r.trim()}</button>`).join(""));
  return text.split(/\n{2,}/).map(block => {
    const lines = block.split("\n");
    if (lines.every(l => /^\s*[-*•]\s+/.test(l)))
      return "<ul>" + lines.map(l => `<li>${inline(l.replace(/^\s*[-*•]\s+/, ""))}</li>`).join("") + "</ul>";
    return `<p>${lines.map(inline).join("<br>")}</p>`;
  }).join("");
}

function renderSources(sources, id) {
  if (!sources.length) return "";
  return '<ul class="sources">' + sources.map(s => `
    <li id="${id}-${s.ref}"><details>
      <summary><span class="ref">${s.ref}</span><span class="kind ${s.kind}">${s.kind}</span>
        <span>${esc(s.title)}</span><span class="where">${esc(s.locator)}</span></summary>
      <div class="snippet">${esc(s.snippet)}${safeUrl(s.url) ? `\n<a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.url)}</a>` : ""}</div>
    </details></li>`).join("") + "</ul>";
}

function add(cls, html) {
  const el = document.createElement("div");
  el.className = "msg " + cls;
  el.innerHTML = html;
  log.appendChild(el);
  el.scrollIntoView({behavior: "smooth", block: "end"});
  return el;
}

async function ask(question) {
  document.getElementById("examples")?.remove();
  add("user", esc(question));
  const pending = add("bot", '<div class="bubble typing">Looking that up…</div>');
  send.disabled = true;
  try {
    const res = await fetch("/api/chat", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({message: question, history: boundedHistory(history)}),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(errorMessage(data.detail));
    const id = "m" + messageId++;
    pending.innerHTML = `<div class="bubble">${renderAnswer(data.answer, id)}</div>` +
      renderSources(data.sources, id) +
      `<div class="meta">${data.sources.length ? data.sources.length + " source(s)" : "No sources cited"}` +
      `${data.used_web ? " · includes web results" : ""} · ${(data.latency_ms / 1000).toFixed(1)}s</div>`;
    history = boundedHistory([...history, {role: "user", content: question}, {role: "assistant", content: data.answer}]);
  } catch (err) {
    pending.classList.add("error");
    pending.innerHTML = `<div class="bubble">${esc(err.message)}</div>`;
  } finally {
    send.disabled = false;
    input.focus();
    pending.scrollIntoView({behavior: "smooth", block: "end"});
  }
}

form.addEventListener("submit", e => {
  e.preventDefault();
  const q = input.value.trim();
  if (!q || send.disabled) return;
  input.value = "";
  ask(q);
});
log.addEventListener("click", e => {
  if (e.target.matches(".examples button")) return ask(e.target.textContent);
  const cite = e.target.closest(".cite");
  if (!cite) return;
  const card = document.getElementById(cite.dataset.target);
  if (!card) return;
  card.querySelector("details").open = true;
  card.classList.add("flash");
  card.scrollIntoView({behavior: "smooth", block: "nearest"});
  setTimeout(() => card.classList.remove("flash"), 1200);
});

document.getElementById("clear").addEventListener("click", () => {
  if (send.disabled) return;
  history = [];
  log.replaceChildren();
  input.focus();
});
