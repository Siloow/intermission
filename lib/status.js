// The status strip: one dot per moving part, in the nav of every page.
// Green is fine, amber is fine-but-look, red is broken, grey is unknown.
// Hover a dot for what it is doing, and how to fix it when it isn't.
const PARTS = [
  ["resolume", "Resolume"], ["live", "Live"], ["player", "Player"],
  ["blender", "Blender"], ["artnet", "Art-Net"], ["screen", "Screen"],
];

const css = document.createElement("style");
css.textContent = `
  #health{display:flex;gap:10px;align-items:center;margin-left:auto;font:12px/1 -apple-system,Helvetica,sans-serif;color:#9aa0ab}
  #health span{display:inline-flex;align-items:center;gap:5px;cursor:default;white-space:nowrap}
  #health i{width:8px;height:8px;border-radius:50%;background:#555;display:inline-block}
  #health .ok i{background:#4cc36e} #health .warn i{background:#e0a93b}
  #health .bad i{background:#e0533b} #health .bad{color:#e8b1a6}
  #health .panic{color:#15161a;background:#e0533b;padding:3px 7px;border-radius:5px;font-weight:700}
  #health .panic i{background:#15161a}
  @media (max-width:900px){ #health b{display:none} }`;
document.head.appendChild(css);

const nav = document.querySelector("nav");
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
