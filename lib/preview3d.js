// 3D preview for the floor-plan editor: the room, the screen and the beams,
// built from the same rig the plan draws. It is a sanity check for aim and
// coverage, not a render - Blender stays the place you judge how it looks.
//
// Beam colours come from /status.json, which the previz writes while it runs,
// so what you see here is what Resolume is actually sending.
import * as THREE from "./three.module.min.js";

const canvas = document.getElementById("gl");
const noteEl = document.getElementById("gl-note");
const renderer = new THREE.WebGLRenderer({canvas, antialias: true});
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.15;

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x07080a);
const camera = new THREE.PerspectiveCamera(45, 1, 0.05, 400);

// ------------------------------------------------------------------ orbit ---
// Minimal orbit/pan/zoom, so the page needs no controls library.
const orbit = {target: new THREE.Vector3(0, 1.2, -0.5), yaw: 0, pitch: 0.35, dist: 9};
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

// Keep the camera inside the room: never under the floor, never through a wall,
// never behind the screen. Bounds come from the venue, with a little margin.
function bounds(){
  const v = venue();
  const hw = v.room_width / 2 - 0.4;
  return {
    x: [-hw, hw],
    y: [0.25, (v.room_height ?? 8.5) - 0.6],
    z: [-v.screen_from_performer + 0.4, v.first_row_from_screen - v.screen_from_performer + 15],
  };
}

function place(){
  const b = bounds();
  orbit.pitch = clamp(orbit.pitch, 0.02, 1.5);       // never look up from below
  orbit.dist = clamp(orbit.dist, 0.6, 40);
  orbit.target.set(clamp(orbit.target.x, b.x[0], b.x[1]),
                   clamp(orbit.target.y, 0.1, 8.0),
                   clamp(orbit.target.z, b.z[0], b.z[1]));
  const p = orbit.pitch, d = orbit.dist;
  let pos = new THREE.Vector3(
    orbit.target.x + Math.sin(orbit.yaw) * Math.cos(p) * d,
    orbit.target.y + Math.sin(p) * d,
    orbit.target.z + Math.cos(orbit.yaw) * Math.cos(p) * d);
  // if that lands outside the room, pull the camera in along its own line of
  // sight until it fits, so the view direction is kept
  const dir = pos.clone().sub(orbit.target);
  let t = 1;
  const limit = (val, from, lo, hi) => {
    if (val > hi && val !== from) t = Math.min(t, (hi - from) / (val - from));
    if (val < lo && val !== from) t = Math.min(t, (lo - from) / (val - from));
  };
  limit(pos.x, orbit.target.x, b.x[0], b.x[1]);
  limit(pos.y, orbit.target.y, b.y[0], b.y[1]);
  limit(pos.z, orbit.target.z, b.z[0], b.z[1]);
  if (t < 1) pos = orbit.target.clone().addScaledVector(dir, Math.max(0.02, t));
  // last word: stay inside the room even when the line of sight is very short
  pos.set(clamp(pos.x, b.x[0], b.x[1]), clamp(pos.y, b.y[0], b.y[1]), clamp(pos.z, b.z[0], b.z[1]));
  camera.position.copy(pos);
  camera.lookAt(orbit.target);
}
let drag = null;
canvas.addEventListener("pointerdown", e => {
  drag = {x: e.clientX, y: e.clientY, pan: e.shiftKey, moved: false};
  canvas.setPointerCapture(e.pointerId);
});
canvas.addEventListener("pointermove", e => {
  if (!drag) return;
  const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
  drag.x = e.clientX; drag.y = e.clientY;
  if (Math.abs(dx) + Math.abs(dy) > 2) drag.moved = true;
  if (drag.pan){
    const right = new THREE.Vector3().setFromMatrixColumn(camera.matrix, 0);
    const up = new THREE.Vector3().setFromMatrixColumn(camera.matrix, 1);
    const k = orbit.dist * 0.0016;
    orbit.target.addScaledVector(right, -dx * k).addScaledVector(up, dy * k);
  } else {
    orbit.yaw -= dx * 0.006;
    orbit.pitch = clamp(orbit.pitch + dy * 0.005, 0.02, 1.5);
  }
  place();
});
canvas.addEventListener("pointerup", e => {
  if (drag && !drag.moved) pick(e);
  drag = null;
});
canvas.addEventListener("wheel", e => {
  e.preventDefault();
  orbit.dist = clamp(orbit.dist * (e.deltaY < 0 ? 0.9 : 1.1), 0.6, 40);
  place();
}, {passive: false});

document.getElementById("gl-seat").onclick = () => {
  // eye at the performer's head, looking at the screen
  const v = venue();
  orbit.target.set(0, 1.35, -v.screen_from_performer);
  orbit.yaw = 0; orbit.pitch = 0.02; orbit.dist = Math.max(0.8, v.screen_from_performer - 0.3);
  place();
};
document.getElementById("gl-top").onclick = () => {
  orbit.target.set(0, 0, 0.5); orbit.yaw = 0; orbit.pitch = 1.1; orbit.dist = 9; place();
};

// ------------------------------------------------------------------ scene ---
const venue = () => window.__venue ||
  {screen_width: 11.5, screen_height: 6, screen_bottom: 1.3,
   screen_from_performer: 1.8, first_row_from_screen: 4, room_width: 15, room_height: 8.5};

const mat = (c, rough = 0.95) => new THREE.MeshStandardMaterial({color: c, roughness: rough});
const box = (w, h, d, m, x, y, z) => {
  const b = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), m);
  b.position.set(x, y, z);
  return b;
};

// Three's Y is up and Z comes toward the viewer, so the room's +y (toward the
// audience) becomes +z here, and the room's z (up) becomes y.
function buildRoom(){
  const g = new THREE.Group();
  const v = venue();
  const depth = v.first_row_from_screen + 16;
  g.add(box(v.room_width, 0.2, depth + 8, mat(0x17181c), 0, -0.1, depth / 2 - v.screen_from_performer - 2));

  // screen with its masking
  const sw = v.screen_width, sh = v.screen_height ?? 6,
        bottom = v.screen_bottom ?? 1.3, sz = -v.screen_from_performer;
  const screenMat = new THREE.MeshBasicMaterial({color: 0x9aa6c8});
  const screen = new THREE.Mesh(new THREE.PlaneGeometry(sw, sh), screenMat);
  screen.position.set(0, bottom + sh / 2, sz + 0.02);
  g.add(screen);
  g.userData.screen = screenMat;
  const black = mat(0x050506, 1);
  g.add(box(sw + 1.2, 0.6, 0.1, black, 0, bottom + sh + 0.3, sz));
  g.add(box(sw + 1.2, 0.6, 0.1, black, 0, bottom - 0.3, sz));
  g.add(box(0.6, sh, 0.1, black, -sw / 2 - 0.3, bottom + sh / 2, sz));
  g.add(box(0.6, sh, 0.1, black, sw / 2 + 0.3, bottom + sh / 2, sz));

  // a soft glow from the screen, so the room is not lit only by the pars
  const glow = new THREE.PointLight(0x8899cc, 30, 40, 2);
  glow.position.set(0, bottom + sh / 2, sz + 1.5);
  g.add(glow);
  g.userData.glow = glow;

  // seating: one block per row, stepped
  const seat = mat(0x2a0d10, 0.85);
  let z = v.first_row_from_screen - v.screen_from_performer, y = -0.35;
  for (let i = 0; i < 14; i++){
    g.add(box(v.room_width - 4, 0.45, 0.5, seat, 0, y + 0.22, z));
    z += 1; y += 0.18;
  }

  // you
  const skin = mat(0x3a3d44, 0.7);
  g.add(box(0.44, 0.7, 0.26, skin, 0, 0.8, 0));
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.12, 16, 12), skin);
  head.position.set(0, 1.3, 0);
  g.add(head);
  g.add(box(0.44, 0.46, 0.44, mat(0x101114, 0.5), 0, 0.23, 0));

  scene.add(new THREE.HemisphereLight(0x33405c, 0x0a0a0c, 0.35));
  scene.add(g);
  return g;
}
const room = buildRoom();

// ------------------------------------------------------------------ beams ---
const beamMaterial = color => new THREE.ShaderMaterial({
  transparent: true, depthWrite: false, side: THREE.DoubleSide,
  blending: THREE.AdditiveBlending,
  uniforms: {uColor: {value: new THREE.Color(color)}, uStrength: {value: 0.0}},
  vertexShader: `
    varying vec2 vUv; varying vec3 vN; varying vec3 vV;
    void main(){
      vUv = uv;
      vec4 wp = modelMatrix * vec4(position, 1.0);
      vN = normalize(mat3(modelMatrix) * normal);
      vV = normalize(cameraPosition - wp.xyz);
      gl_Position = projectionMatrix * viewMatrix * wp;
    }`,
  fragmentShader: `
    uniform vec3 uColor; uniform float uStrength;
    varying vec2 vUv; varying vec3 vN; varying vec3 vV;
    void main(){
      float along = pow(1.0 - vUv.y, 1.4);              // fades away from the lens
      float edge = pow(1.0 - abs(dot(normalize(vN), normalize(vV))), 1.2);
      float a = uStrength * along * (0.12 + 0.88 * edge);   // mostly the silhouette
      if (a < 0.002) discard;
      gl_FragColor = vec4(uColor * (0.6 + 0.8 * uStrength), a);
    }`,
});

// fixture profiles, so a bar is drawn at its real length with its real pixels
let profiles = {};
fetch("fixtures.json", {cache: "no-store"}).then(r => r.json())
  .then(d => { profiles = d.profiles || {}; syncFixtures(); }).catch(() => {});
const profOf = f => profiles[f.profile] || {};
const kindOf = f => profOf(f).kind || "par";

const fixtures = new Map();     // name -> {group, cone, light, lens, mat}
const canGeom = new THREE.CylinderGeometry(0.11, 0.11, 0.2, 20);
const lensGeom = new THREE.CircleGeometry(0.1, 20);
const coneGeom = (() => {
  const g = new THREE.ConeGeometry(1, 1, 28, 1, true);
  g.translate(0, -0.5, 0);      // apex at the origin, opening along -Y
  return g;
})();
const DOWN = new THREE.Vector3(0, -1, 0);

function aimVector(f){
  const a = (f.aim_deg || 0) * Math.PI / 180, t = (f.tilt_deg ?? 70) * Math.PI / 180;
  // plan x -> three x, plan y -> three z, up -> three y
  return new THREE.Vector3(Math.sin(a) * Math.cos(t), Math.sin(t), Math.cos(a) * Math.cos(t)).normalize();
}

function buildBar(f){
  const p = profOf(f), body = p.body || {length: 1.04, width: 0.09, height: 0.144};
  const n = p.pixels || 18;
  const group = new THREE.Group();
  const housing = new THREE.Mesh(
    new THREE.BoxGeometry(body.length, body.height, body.width), mat(0x0a0a0b, 0.5));
  group.add(housing);
  const pixels = [];
  const pxGeom = new THREE.PlaneGeometry(body.length / n * 0.72, body.width * 0.68)
    .rotateX(-Math.PI / 2);
  for (let i = 0; i < n; i++){
    const m = new THREE.MeshBasicMaterial({color: 0x222222});
    const q = new THREE.Mesh(pxGeom, m);
    q.position.set(-body.length / 2 + body.length / n * (i + 0.5), body.height / 2 + 0.002, 0);
    group.add(q);
    pixels.push(m);
  }
  const bm = beamMaterial(0xffffff);
  const cone = new THREE.Mesh(coneGeom, bm);
  const light = new THREE.SpotLight(0xffffff, 0, 30, 0.4, 0.5, 1.6);
  group.add(cone, light, light.target);
  housing.userData.pick = f.name;
  const ring = new THREE.Mesh(
    new THREE.RingGeometry(0.16, 0.2, 24).rotateX(-Math.PI / 2),
    new THREE.MeshBasicMaterial({color: 0xffd54a, transparent: true, opacity: 0.9}));
  ring.position.y = -0.09;
  group.add(ring);
  scene.add(group);
  return {group, cone, light, beam: bm, can: housing, ring, pixels, isBar: true};
}

function syncFixtures(){
  const rig = window.__rig;
  if (!rig) return;
  const seen = new Set();
  rig.fixtures.forEach((f, i) => {
    seen.add(f.name);
    let fx = fixtures.get(f.name);
    if (fx && !!fx.isBar !== (kindOf(f) === "bar")){     // kind changed under us
      scene.remove(fx.group); fixtures.delete(f.name); fx = null;
    }
    if (!fx && kindOf(f) === "bar"){
      fx = buildBar(f);
      fixtures.set(f.name, fx);
    }
    if (!fx){
      const group = new THREE.Group();
      const can = new THREE.Mesh(canGeom, mat(0x0a0a0b, 0.5));
      const lensMat = new THREE.MeshBasicMaterial({color: 0x222222});
      const lens = new THREE.Mesh(lensGeom, lensMat);
      const bm = beamMaterial(0xffffff);
      const cone = new THREE.Mesh(coneGeom, bm);
      const light = new THREE.SpotLight(0xffffff, 0, 30, 0.4, 0.4, 1.6);
      light.target.position.set(0, 0, 0);
      group.add(can, lens, cone, light, light.target);
      can.userData.pick = f.name;
      scene.add(group);
      const ring = new THREE.Mesh(
        new THREE.RingGeometry(0.16, 0.2, 24).rotateX(-Math.PI / 2),
        new THREE.MeshBasicMaterial({color: 0xffd54a, transparent: true, opacity: 0.9}));
      ring.position.y = -0.09;
      group.add(ring);
      fx = {group, cone, light, lens: lensMat, beam: bm, can, ring};
      fixtures.set(f.name, fx);
    }
    const reach = 5;                       // how far a beam is drawn, in metres
    const dir = aimVector(f);
    const spread = Math.tan((f.beam_deg ?? 25) * Math.PI / 360) * reach;
    fx.group.position.set(f.x, f.z ?? (fx.isBar ? 0.07 : 0.18), f.y);
    fx.cone.scale.set(spread, reach, spread);
    fx.cone.quaternion.setFromUnitVectors(DOWN, dir);
    if (fx.lens) fx.lens.needsUpdate = true;
    fx.can.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir);
    if (fx.isBar){
      // a bar lies flat: aimed like a par, then turned about its own long axis,
      // and its beam is a wide wedge rather than a cone
      const q = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir);
      const spin = new THREE.Quaternion().setFromAxisAngle(
        new THREE.Vector3(0, 1, 0), -(f.rot_deg || 0) * Math.PI / 180);
      fx.group.quaternion.copy(spin.multiply(q));
      fx.can.quaternion.identity();
      fx.cone.quaternion.setFromUnitVectors(DOWN, new THREE.Vector3(0, 1, 0));
      fx.cone.scale.set(spread * 3.5, reach, spread);
    }
    fx.light.angle = Math.max(0.05, (f.beam_deg ?? 25) * Math.PI / 360);
    fx.light.target.position.copy(dir.clone().multiplyScalar(8));
    fx.group.userData.selected = (window.__selSet || []).includes(i);
    fx.ring.visible = fx.group.userData.selected;
  });
  for (const [name, fx] of fixtures){
    if (!seen.has(name)){ scene.remove(fx.group); fixtures.delete(name); }
  }
}

// ----------------------------------------------------------------- colours --
// What lights the room is chosen on the floor plan (window.__roomSource):
//   live — what the previz is receiving from Resolume (/status.json)
//   look — the look being designed; loop — a control-band loop playing in the
//   browser. Both of those arrive as window.__roomColours, in the same shape the
//   previz reports: {name: {r, g, b, w, dim, pixels?: [[r, g, b, w], ...]}}.
let lastStatus = {}, statusAge = 999;
async function pollStatus(){
  try{
    const r = await fetch("status.json", {cache: "no-store"});
    lastStatus = await r.json();
    statusAge = lastStatus.t ? (Date.now() / 1000 - lastStatus.t) : 999;
  }catch(e){ lastStatus = {}; }
  setTimeout(pollStatus, 250);
}

function applyColours(){
  const s = lastStatus;
  const live = !!(s.live && statusAge < 3);
  const src = window.__roomSource || "live";
  const table = src === "live" ? ((live && s.pars) || {}) : (window.__roomColours || {});
  noteEl.textContent =
      src === "live" ? (live ? `live from the previz${s.artnet_pps ? ` · ${s.artnet_pps} pkt/s` : ""}`
                             : "live: the previz isn't running")
    : src === "loop" ? `loop: ${window.__roomLabel || ""}`
    : (window.__lookName ? `look: ${window.__lookName}` : "no look chosen");
  for (const [name, fx] of fixtures){
    const p = table[name] || null;
    const dim = p ? (p.dim ?? 255) / 255 : 0;
    const w = p ? (p.w || 0) / 255 : 0;
    const col = p
      ? new THREE.Color(Math.min(1, (p.r || 0) / 255 + w), Math.min(1, (p.g || 0) / 255 + w * 0.92),
                        Math.min(1, (p.b || 0) / 255 + w * 0.82))
      : new THREE.Color(0.5, 0.55, 0.7);
    const level = p ? dim * Math.max(col.r, col.g, col.b) : (fx.group.userData.selected ? 0.22 : 0.1);
    fx.beam.uniforms.uColor.value.copy(col);
    fx.beam.uniforms.uStrength.value = 0.03 + level * 0.3;
    fx.light.color.copy(col);
    fx.light.intensity = level * 26;
    if (fx.lens) fx.lens.color.copy(col).multiplyScalar(0.4 + level * 0.6);
    if (fx.pixels){                              // a bar: colour each LED
      const rows = (p && p.pixels) || null;
      fx.pixels.forEach((m, i) => {
        const v = rows && rows[i];
        if (v){
          const w = (v[3] || 0) / 255;
          m.color.setRGB(Math.min(1, v[0] / 255 + w),
                         Math.min(1, v[1] / 255 + w * 0.92),
                         Math.min(1, v[2] / 255 + w * 0.82));
        } else {
          m.color.copy(col).multiplyScalar(0.35 + level * 0.65);
        }
      });
    }
  }
  if (src === "live" && live && s.screen_rgb){
    room.userData.screen.color.setRGB(...s.screen_rgb);
    room.userData.glow.color.setRGB(...s.screen_rgb);
    room.userData.glow.intensity = 12 + 40 * Math.max(...s.screen_rgb);
  }
}

// ---------------------------------------------------------------- picking ---
const ray = new THREE.Raycaster();
function pick(e){
  const add = e.shiftKey || e.metaKey;
  const r = canvas.getBoundingClientRect();
  const pt = new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1,
                               -((e.clientY - r.top) / r.height) * 2 + 1);
  ray.setFromCamera(pt, camera);
  const meshes = [...fixtures.values()].map(f => f.can);
  const hit = ray.intersectObjects(meshes, false)[0];
  if (!hit) return;
  const name = hit.object.userData.pick;
  const i = (window.__rig?.fixtures || []).findIndex(f => f.name === name);
  if (i >= 0) document.dispatchEvent(new CustomEvent("rig:select", {detail: {index: i, add}}));
}

// ------------------------------------------------------------------- loop ---
function resize(){
  const w = canvas.clientWidth, h = canvas.clientHeight;
  if (!w || !h) return;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
addEventListener("resize", resize);
document.addEventListener("rig:changed", syncFixtures);
document.addEventListener("look:changed", () => {});   // colours are picked up by the poll

window.__preview = {camera, orbit, place, bounds};
place();
resize();
syncFixtures();
pollStatus();
(function loop(){
  requestAnimationFrame(loop);
  resize();
  applyColours();                               // every frame, so a playing loop moves smoothly
  renderer.render(scene, camera);
})();
