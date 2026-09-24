// The control band in the browser: plays a loop (or renders a look) onto a
// 1920x120 canvas, tints it, and samples it at each fixture's points from
// band.py's layout — what Resolume's Lumiverse will read. The floor plan uses
// this to light its fixtures and the 3D preview with a loop.
(function(){
  // the same as band.py rgb_of(): RGBW + dim as the RGB the band carries
  function rgbOf(v){
    const k = (v.dim ?? 255) / 255, w = v.w || 0;
    return [(v.r || 0) + w, (v.g || 0) + w * 0.92, (v.b || 0) + w * 0.82].map(c => Math.min(255, c) * k);
  }

  class BandPlayer {
    constructor(){
      this.layout = null; this.clips = null;
      this.current = null;                         // {kind: "loop"|"look", ...}
      this.tint = null;                            // "#rrggbb" or null
      this.bpm = null;
      this.samples = {};                           // name -> [[r,g,b], ...] one per sample point
      this.video = document.createElement("video");
      Object.assign(this.video, {muted: true, loop: true, playsInline: true});
      this.src = document.createElement("canvas");
      this.ctx = this.src.getContext("2d", {willReadFrequently: true});
    }

    async load(){
      this.layout = await (await fetch("band/layout", {cache: "no-store"})).json();
      this.clips = await (await fetch("band/clips", {cache: "no-store"})).json();
      this.src.width = this.layout.width; this.src.height = this.layout.height;
      this.bpm = this.bpm || this.clips.tempo || this.clips.loop_bpm || 120;
      return this;
    }
    async reloadLayout(){                          // after the rig changed: addresses set the order
      this.layout = await (await fetch("band/layout", {cache: "no-store"})).json();
    }

    playLoop(loop){
      this.current = Object.assign({kind: "loop"}, loop);
      this.video.src = "content/light-loops/" + encodeURIComponent(loop.file);
      this.setBpm(this.bpm);
      this.video.play().catch(() => {});
    }
    showLook(look){
      this.current = Object.assign({kind: "look"}, look);
      this.video.pause();
    }
    stop(){ this.current = null; this.video.pause(); }
    toggle(){ if (this.current && this.current.kind === "loop") this.video.paused ? this.video.play() : this.video.pause(); }
    get paused(){ return this.video.paused; }

    setBpm(bpm){
      this.bpm = +bpm || this.bpm;
      const base = this.clips && this.clips.loop_bpm;
      this.video.playbackRate = base ? Math.max(0.25, Math.min(4, this.bpm / base)) : 1;
    }
    rateNote(){
      const base = this.clips && this.clips.loop_bpm, r = this.video.playbackRate;
      if (!base) return "";
      return Math.abs(r - 1) < 0.005 ? `written at ${base} bpm` : `written at ${base}, playing ×${r.toFixed(2)}`;
    }
    counter(){
      const c = this.current;
      if (!c || c.kind !== "loop" || !this.video.duration) return c && c.kind === "look" ? "still" : "—";
      const bars = c.bars || 1, beat = this.video.currentTime / this.video.duration * bars * 4;
      return `bar ${Math.floor(beat / 4) + 1}/${bars} · beat ${Math.floor(beat % 4) + 1}`;
    }

    // draw this frame onto the band and sample it
    frame(){
      const L = this.layout, c = this.current;
      if (!L || !c) return false;
      const W = L.width, H = L.height, g = this.ctx;
      g.globalCompositeOperation = "source-over";
      g.fillStyle = "#000"; g.fillRect(0, 0, W, H);
      if (c.kind === "loop"){
        if (this.video.readyState >= 2) g.drawImage(this.video, 0, 0, W, H);
      } else {
        for (const cell of L.cells){
          const v = (c.fixtures || {})[cell.name];
          if (!v) continue;
          g.fillStyle = `rgb(${rgbOf(v).map(Math.round)})`;
          g.fillRect(cell.x0, 0, cell.x1 - cell.x0, H);
        }
      }
      if (this.tint){                              // Colorize: white becomes the colour
        g.globalCompositeOperation = "multiply";
        g.fillStyle = this.tint; g.fillRect(0, 0, W, H);
        g.globalCompositeOperation = "source-over";
      }
      const img = g.getImageData(0, 0, W, H).data, y = H >> 1;
      const at = x => {                            // a small area, like the Lumiverse
        let r = 0, gg = 0, b = 0, n = 0;
        for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++){
          const xx = Math.max(0, Math.min(W - 1, x + dx)), i = ((y + dy) * W + xx) * 4;
          r += img[i]; gg += img[i + 1]; b += img[i + 2]; n++;
        }
        return [r / n, gg / n, b / n];
      };
      this.samples = {};
      for (const cell of L.cells) this.samples[cell.name] = cell.samples.map(at);
      return true;
    }

    // what each fixture shows, in the shape the previz reports: {r,g,b,w,dim,pixels}
    colours(){
      const out = {};
      for (const [name, s] of Object.entries(this.samples)){
        const avg = s.reduce((a, v) => a.map((x, i) => x + v[i] / s.length), [0, 0, 0]);
        out[name] = {r: avg[0], g: avg[1], b: avg[2], w: 0, dim: 255,
                     pixels: s.length > 1 ? s.map(v => [v[0], v[1], v[2], 0]) : undefined};
      }
      return out;
    }

    // the band with each fixture's cell and sample points on top
    drawStrip(cv, overlay){
      const L = this.layout;
      if (!L) return;
      const g = cv.getContext("2d"), W = L.width, top = overlay ? 26 : 0, H = cv.height - top;
      g.clearRect(0, 0, cv.width, cv.height);
      g.drawImage(this.src, 0, top, W, H);
      if (!overlay) return;
      g.font = "600 22px -apple-system, Helvetica, sans-serif";
      g.textAlign = "center";
      for (const cell of L.cells){
        g.strokeStyle = "rgba(255,255,255,.35)"; g.lineWidth = 2;
        g.strokeRect(cell.x0 + 1, top + 1, cell.x1 - cell.x0 - 2, H - 2);
        g.fillStyle = "#9aa0ac";
        g.fillText(cell.name, (cell.x0 + cell.x1) / 2, top - 5);
        (this.samples[cell.name] || []).forEach((rgb, k) => {
          const r = cell.kind === "bar" ? 5 : 11;
          g.beginPath(); g.arc(cell.samples[k], top + H / 2, r, 0, Math.PI * 2);
          g.fillStyle = `rgb(${rgb.map(Math.round)})`; g.fill();
          g.lineWidth = cell.kind === "bar" ? 1.5 : 3; g.strokeStyle = "#fff"; g.stroke();
        });
      }
    }
  }

  window.BandPlayer = BandPlayer;
  window.bandRgbOf = rgbOf;
})();
