// The status strip: one dot per moving part, in the nav of every page.
// Green is fine, amber is fine-but-look, red is broken, grey is unknown.
// Hover a dot for what it is doing, and how to fix it when it isn't.
const PARTS = [
  ["resolume", "Resolume"], ["live", "Live"], ["player", "Player"],
  ["blender", "Blender"], ["artnet", "Art-Net"], ["screen", "Screen"],
];

const css = document.createElement("style");
css.textContent = `
  #health{display:flex;gap:12px;align-items:center;margin-left:auto;font-size:var(--fs-xs,11px);
    color:var(--text-2,#9aa0ab);white-space:nowrap}
  #health span{display:inline-flex;align-items:center;gap:5px;cursor:default}
  #health i{width:7px;height:7px;border-radius:50%;background:var(--text-3,#555);display:inline-block}
  #health .ok i{background:var(--ok,#4cc36e);box-shadow:0 0 6px rgba(79,199,135,.6)}
  #health .warn i{background:var(--warn,#e0a93b)}
  #health .bad i{background:var(--err,#e0533b)}
  #health .bad{color:#f0b3a8}
  #health .panic{color:var(--accent-ink,#15161a);background:var(--err,#e0533b);padding:2px 8px;border-radius:9px;font-weight:700}
  #health .panic i{background:var(--accent-ink,#15161a)}
  @media (max-width:1100px){ #health b{display:none} #health{gap:8px} }`;
document.head.appendChild(css);

const nav = document.querySelector(".topbar") || document.querySelector("nav");
const box = document.createElement("div");
box.id = "health";
box.innerHTML = PARTS.map(([k, label]) =>
  `<span data-k="${k}"><i></i><b>${label}</b></span>`).join("");
// docs has a spacer and a title on the right; keep the dots before the title
const spacer = nav && nav.querySelector(".spacer");
if (spacer) { spacer.after(box); box.style.marginLeft = "0"; box.style.marginRight = "12px"; }
else if (nav) nav.appendChild(box);

function paint(h) {
  for (const [k, label] of PARTS) {
    const el = box.querySelector(`[data-k="${k}"]`);
    const p = h ? h[k] || {} : {ok: false, text: "the editor server stopped", fix: "Start Test.command"};
    const panic = k === "player" && /PANIC/.test(p.text || "");
    el.className = panic ? "panic" : p.ok === null ? "" : p.warn ? "warn" : p.ok ? "ok" : "bad";
    el.title = `${label}: ${p.text || ""}` + (p.fix ? `\n→ ${p.fix}` : "");
  }
}

async function poll() {
  try {
    paint(await (await fetch("/health", {cache: "no-store"})).json());
  } catch { paint(null); }
  setTimeout(poll, 1500);
}
poll();
