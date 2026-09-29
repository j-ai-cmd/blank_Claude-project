import * as THREE from "three";
import type { Employee, Office, Presence } from "../lib/types";

/**
 * The 3D office. Knows nothing about the backend: the controller tells it who is in what state and which
 * note to walk where. Floor plan is built from GET /api/office, so new departments get a desk block automatically.
 */

export const DEPT_COLORS: Record<string, number> = { marketing: 0xe46a9c, sales: 0x4fb3e8, recruiting: 0xa27ff0, ops: 0x5fcf96, hq: 0xffd35c };
const EXTRA_COLORS = [0xf09a4a, 0x4fd1c5, 0xe0c341, 0x8fa3ff];
export function deptColor(id: string, i = 0) { return DEPT_COLORS[id] ?? EXTRA_COLORS[i % EXTRA_COLORS.length]; }

const SKIN = [0xf1c7a1, 0xd9a47c, 0xa8744f, 0x7b4f32, 0xe8b894, 0xc68b62];
const HAIR = [0x3b2a1e, 0x1d1a18, 0x8a5a2b, 0xd9b36b, 0x5b3a26, 0xb0482c];
const WALK_X = 3.7;
const SPEED = 4.2; // units per second at 1x

type PoseKey = "hipY" | "legX" | "torsoX" | "headX" | "headY" | "armL" | "armR";
type Pose = Record<PoseKey, number>;

interface Station { group?: THREE.Group; screenMat?: THREE.MeshLambertMaterial; glow?: THREE.MeshBasicMaterial; deskTop: THREE.Vector3; lit?: boolean }

export interface Character {
  id: string; name: string; kind: string; dept: string; color: number;
  root: THREE.Group; hips: THREE.Group; torso: THREE.Group; neck: THREE.Group; head: THREE.Mesh;
  arms: THREE.Group[]; legs: THREE.Group[]; hand: THREE.Group; eyes: THREE.Mesh[];
  pose: Pose; seat: THREE.Vector3; seatRotY: number; stand: THREE.Vector3; station: Station;
  presence: Presence | "owner"; walking: boolean; carrying: boolean; handing: boolean; pop: number;
  path: THREE.Vector3[]; onArrive: (() => void) | null; lock: Promise<void>;
}

interface Note { id: string; mesh: THREE.Mesh; holder: string; inHand: boolean; n: number }

export interface LabelSink { (key: string, x: number, y: number, visible: boolean): void }

export class OfficeEngine {
  renderer: THREE.WebGLRenderer;
  scene = new THREE.Scene();
  camera = new THREE.PerspectiveCamera(42, 1, 0.1, 250);
  chars: Record<string, Character> = {};
  notes: Record<string, Note> = {};
  speed = 1;
  onPick: (p: { emp?: string; task?: string }) => void = () => {};
  onWalking: (id: string, walking: boolean) => void = () => {};
  onHover: (id: string | null) => void = () => {};
  onFocus: (key: string) => void = () => {};
  private hovered: string | null = null;
  private rugs: THREE.Mesh[] = [];
  labelSink: LabelSink = () => {};

  private pickables: THREE.Object3D[] = [];
  private mats = new Map<string, THREE.Material>();
  private tweens = new Set<{ ms: number; t: number; step: (k: number) => void; res: () => void }>();
  private signs: { key: string; pos: THREE.Vector3 }[] = [];
  private crossLanes: number[] = [];
  private cam = { target: new THREE.Vector3(0, 0, -2), radius: 42, theta: 0, phi: 0.95 };
  private camGoal: { target: THREE.Vector3; radius: number } | null = null;
  private following: string | null = null;
  private raf = 0;
  private abort = new AbortController();
  private clock = 0;
  private last = performance.now();
  private noteN = 0;
  focusPoints: Record<string, { target: THREE.Vector3; radius: number }> = {};

  constructor(private canvas: HTMLCanvasElement) {
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.scene.background = new THREE.Color(0x121826);
    this.scene.fog = new THREE.Fog(0x121826, 60, 110);
    this.scene.add(new THREE.HemisphereLight(0xdfe8ff, 0x3a2f22, 2.2));
    const sun = new THREE.DirectionalLight(0xfff1dc, 2.4);
    sun.position.set(14, 26, 16);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    Object.assign(sun.shadow.camera, { left: -28, right: 28, top: 28, bottom: -28, near: 1, far: 80 });
    sun.shadow.bias = -0.0008;
    this.scene.add(sun);
    this.bindInput();
    this.resize();
    window.addEventListener("resize", this.resize);
    this.raf = requestAnimationFrame(this.frame);
  }

  dispose() {
    cancelAnimationFrame(this.raf);
    this.abort.abort();
    window.removeEventListener("resize", this.resize);
    this.renderer.dispose();
  }

  // ================================================================ building
  private mat(color: number, opts: THREE.MeshLambertMaterialParameters = {}) {
    const key = color + JSON.stringify(opts);
    if (!this.mats.has(key)) this.mats.set(key, new THREE.MeshLambertMaterial({ color, ...opts }));
    return this.mats.get(key)!;
  }
  private box(w: number, h: number, d: number, m: THREE.Material | THREE.Material[], x = 0, y = 0, z = 0, parent?: THREE.Object3D) {
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), m);
    mesh.position.set(x, y, z);
    mesh.castShadow = true; mesh.receiveShadow = true;
    (parent ?? this.scene).add(mesh);
    return mesh;
  }
  private rug(x: number, z: number, w: number, d: number, color: number, opacity = 0.3, focusKey?: string) {
    const m = new THREE.Mesh(new THREE.PlaneGeometry(w, d), new THREE.MeshLambertMaterial({ color, transparent: true, opacity }));
    m.rotation.x = -Math.PI / 2; m.position.set(x, 0.01, z); m.receiveShadow = true; this.scene.add(m);
    if (focusKey) { m.userData.focusKey = focusKey; this.rugs.push(m); }
  }
  /** Department name painted on the carpet. */
  private floorText(text: string, x: number, z: number, color: string, width = 6, y = 0.02) {
    const cv = document.createElement("canvas"); cv.width = 1024; cv.height = 128;
    const g = cv.getContext("2d")!;
    const paint = () => {
      g.clearRect(0, 0, cv.width, cv.height);
      let size = 84;
      const label = text.toUpperCase();
      const set = () => { g.font = `700 ${size}px 'Pixelify Sans', 'Courier New', monospace`; (g as any).letterSpacing = `${Math.round(size * 0.18)}px`; };
      set();
      while (g.measureText(label).width > cv.width - 40 && size > 20) { size -= 4; set(); } // shrink to fit
      g.textAlign = "center"; g.textBaseline = "middle"; g.fillStyle = color; g.globalAlpha = 0.85;
      g.fillText(label, cv.width / 2, cv.height / 2 + 4);
      t.needsUpdate = true;
    };
    const t = new THREE.CanvasTexture(cv); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 4;
    paint();
    document.fonts?.ready.then(paint); // repaint once the web font has loaded
    const m = new THREE.Mesh(new THREE.PlaneGeometry(width, width / 8), new THREE.MeshBasicMaterial({ map: t, transparent: true, depthWrite: false }));
    m.rotation.x = -Math.PI / 2; m.position.set(x, y, z); this.scene.add(m);
  }
  private plant(x: number, z: number) {
    this.box(0.6, 0.5, 0.6, this.mat(0x8a5a3b), x, 0.25, z);
    this.box(0.8, 0.8, 0.8, this.mat(0x3f9a4f), x, 0.95, z);
    this.box(0.5, 0.5, 0.5, this.mat(0x53b862), x, 1.55, z);
  }

  build(office: Office) {
    const HEAD_Z = -15;
    let zBack = -9.4;
    let lastLead = zBack;
    const depts = office.departments;
    let idx = 0;
    this.crossLanes = [HEAD_Z - 1.6];
    for (let r = 0; r < Math.ceil(depts.length / 2); r++) {
      const pair = depts.slice(r * 2, r * 2 + 2);
      const rows = Math.max(1, ...pair.map((d) => Math.ceil(d.specialists.length / 4)));
      const zLead = zBack + 3.4 * rows;
      pair.forEach((d, i) => {
        const cx = i === 0 ? -8.5 : 8.5;
        const color = deptColor(d.id, r * 2 + i);
        this.addEmployee(d.lead, cx, zLead, color, idx++);
        d.specialists.forEach((s, k) => {
          const col = k % 4, row = Math.floor(k / 4);
          this.addEmployee(s, cx + (col - 1.5) * 2.2, zLead - 3.4 * (row + 1), color, idx++);
        });
        const zMin = zLead - 3.4 * rows - 1.6, zMax = zLead + 1.6;
        this.rug(cx, (zMin + zMax) / 2, 10.4, zMax - zMin + 0.6, color, 0.28, d.id);
        this.floorText(d.id, cx, zMax + 0.1, "#" + new THREE.Color(color).getHexString(), 9);
        this.focusPoints[d.id] = { target: new THREE.Vector3(cx, 0, zLead - 1.7 * rows), radius: 15 + 2 * rows };
      });
      this.crossLanes.push(zLead + 2.6);
      lastLead = zLead;
      zBack = zLead + 4.8; // next pair's back row sits one aisle in front
    }
    // head table
    this.box(9, 0.3, 4.4, this.mat(0x3a3350), 0, 0.15, HEAD_Z + 0.7);
    this.rug(0, HEAD_Z + 0.7, 9.4, 4.8, 0xffd35c, 0.22, "hq");
    this.floorText("Head table", 0, HEAD_Z + 2.55, "#ffd35c", 7, 0.32);
    const core = Object.values(office.core);
    const order = [...core.filter((e) => e.id === "chief_of_staff"), ...core.filter((e) => e.id !== "chief_of_staff")];
    order.forEach((e, i) => {
      const x = i === 0 ? 0 : (i % 2 ? -1 : 1) * 2.6 * Math.ceil(i / 2);
      const shirt = e.id === "chief_of_staff" ? 0xffd35c : e.id === "verifier" ? 0xf2f2f2 : 0x8a6bd6;
      const c = this.addEmployee(e, x, HEAD_Z, shirt, idx++, 0.3);
      c.stand.set(x, 0, HEAD_Z - 1.6);
    });
    this.focusPoints.hq = { target: new THREE.Vector3(0, 0, HEAD_Z + 1), radius: 15 };
    // owner at the front, facing the office
    const ownerZ = lastLead + 4.4;
    this.addOwner(ownerZ);
    this.crossLanes.push(ownerZ);
    // floor + walls sized to the plan
    const zMinAll = HEAD_Z - 3.5, zMaxAll = ownerZ + 2;
    const depth = zMaxAll - zMinAll, midZ = (zMinAll + zMaxAll) / 2;
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(34, depth), new THREE.MeshLambertMaterial({ map: this.plankTexture(depth) }));
    floor.rotation.x = -Math.PI / 2; floor.position.set(0, 0, midZ); floor.receiveShadow = true; this.scene.add(floor);
    const wall = this.mat(0x2a3346);
    this.box(34, 1.2, 0.4, wall, 0, 0.6, zMinAll);
    this.box(0.4, 1.2, depth, wall, -17, 0.6, midZ);
    this.box(0.4, 1.2, depth, wall, 17, 0.6, midZ);
    [[-15.5, zMinAll + 1.5], [15.5, zMinAll + 1.5], [-15.5, zMaxAll - 1.5], [15.5, zMaxAll - 1.5], [-3.1, ownerZ - 1.9], [3.1, ownerZ - 1.9]]
      .forEach(([x, z]) => this.plant(x, z));
    this.focusPoints.all = { target: new THREE.Vector3(0, 0, midZ), radius: Math.max(40, depth * 1.25) };
    this.cam.target.copy(this.focusPoints.all.target);
    this.cam.radius = this.focusPoints.all.radius * (this.canvas.clientWidth < 700 ? 1.3 : 1);
  }

  private plankTexture(depth: number) {
    const c = document.createElement("canvas"); c.width = c.height = 64;
    const g = c.getContext("2d")!;
    const tones = ["#b99a6b", "#c4a576", "#ae8f61", "#bfa070"];
    for (let r = 0; r < 8; r++) for (let k = -1; k < 5; k++) { g.fillStyle = tones[(r * 3 + k * 5 + 20) % 4]; g.fillRect(k * 16 + (r % 2 ? 8 : 0), r * 8, 16, 8); }
    g.fillStyle = "rgba(60,40,20,.25)"; for (let r = 0; r < 8; r++) g.fillRect(0, r * 8 + 7, 64, 1);
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace; t.magFilter = THREE.NearestFilter; t.wrapS = t.wrapT = THREE.RepeatWrapping; t.repeat.set(8, depth / 4.25);
    return t;
  }

  private makeCharacter(id: string, shirtHex: number, idx: number, leader: boolean, pantsHex = 0x2e3a59) {
    const root = new THREE.Group(), hips = new THREE.Group(), torso = new THREE.Group();
    root.add(hips); hips.add(torso);
    const skin = this.mat(SKIN[idx % SKIN.length]), shirt = this.mat(shirtHex), pants = this.mat(pantsHex);
    const hair = this.mat(HAIR[(idx * 7) % HAIR.length]);
    this.box(0.52, 0.72, 0.3, shirt, 0, 0.36, 0, torso);
    if (leader) this.box(0.14, 0.14, 0.04, this.mat(0xffd35c, { emissive: 0x5a4300 }), 0.12, 0.52, 0.16, torso);
    const neck = new THREE.Group(); neck.position.y = 0.72; torso.add(neck);
    const head = this.box(0.5, 0.5, 0.5, skin, 0, 0.25, 0, neck);
    this.box(0.52, 0.14, 0.52, hair, 0, 0.46, 0, neck);
    this.box(0.52, 0.28, 0.1, hair, 0, 0.33, -0.22, neck);
    const eyeM = this.mat(0x1b1d2a);
    const eyes = [this.box(0.08, 0.08, 0.02, eyeM, -0.11, 0.26, 0.26, neck), this.box(0.08, 0.08, 0.02, eyeM, 0.11, 0.26, 0.26, neck)];
    if (id === "owner") this.box(0.56, 0.12, 0.56, this.mat(0xffd35c, { emissive: 0x6a5000 }), 0, 0.56, 0, neck);
    const arms = [-1, 1].map((s) => {
      const p = new THREE.Group(); p.position.set(s * 0.36, 0.68, 0); torso.add(p);
      this.box(0.2, 0.34, 0.24, shirt, 0, -0.15, 0, p);
      this.box(0.18, 0.36, 0.2, skin, 0, -0.5, 0, p);
      return p;
    });
    const legs = [-1, 1].map((s) => {
      const p = new THREE.Group(); p.position.set(s * 0.13, 0, 0); hips.add(p);
      this.box(0.24, 0.7, 0.26, pants, 0, -0.35, 0, p);
      this.box(0.25, 0.1, 0.3, this.mat(0x1d2230), 0, -0.68, 0.03, p);
      return p;
    });
    const hand = new THREE.Group(); hand.position.set(0, -0.7, 0.08); arms[1].add(hand);
    root.traverse((o) => { if ((o as THREE.Mesh).isMesh) { o.userData.empId = id; this.pickables.push(o); } });
    this.scene.add(root);
    return { root, hips, torso, neck, head, arms, legs, hand, eyes };
  }

  private makeStation(x: number, z: number, big: boolean, y = 0): Station {
    const g = new THREE.Group(); g.position.set(x, y, z); this.scene.add(g);
    const w = big ? 2 : 1.6;
    this.box(w, 0.72, 0.9, this.mat(big ? 0x8a6443 : 0xa87f55), 0, 0.36, 0.95, g);
    this.box(w + 0.06, 0.06, 0.96, this.mat(big ? 0x6d4d33 : 0x8f6a45), 0, 0.75, 0.95, g);
    const monitor = new THREE.Group(); monitor.position.set(0, 1.02, 1.25); g.add(monitor);
    const screenMat = new THREE.MeshLambertMaterial({ color: 0x1b2233, emissive: 0x000000 });
    const back = this.mat(0x2b3040);
    const scr = new THREE.Mesh(new THREE.BoxGeometry(0.78, 0.48, 0.06), [back, back, back, back, back, screenMat]);
    scr.castShadow = true; monitor.add(scr);
    const glow = new THREE.MeshBasicMaterial({ color: 0x2b3040 });
    const strip = new THREE.Mesh(new THREE.BoxGeometry(0.78, 0.04, 0.07), glow); strip.position.y = 0.26; monitor.add(strip);
    this.box(0.1, 0.22, 0.1, back, 0, -0.3, 0, monitor);
    this.box(0.62, 0.1, 0.6, this.mat(0x39415a), 0, 0.45, 0, g);
    this.box(0.62, 0.62, 0.1, this.mat(0x39415a), 0, 0.78, -0.3, g);
    this.box(0.5, 0.03, 0.3, this.mat(0x2a2f3d), 0, 0.795, 0.8, g);
    g.traverse((o) => { if ((o as THREE.Mesh).isMesh) this.pickables.push(o); });
    return { group: g, screenMat, glow, deskTop: new THREE.Vector3(x, 0.8 + y, z + 0.95) };
  }

  private addEmployee(e: Employee, x: number, z: number, color: number, idx: number, y = 0) {
    const leader = e.kind === "lead" || e.kind === "router";
    const station = this.makeStation(x, z, e.kind !== "specialist", y);
    station.group!.traverse((o) => (o.userData.empId = e.id));
    const shirt = e.kind === "specialist" ? new THREE.Color(color).lerp(new THREE.Color(0xffffff), 0.35).getHex() : color;
    const parts = this.makeCharacter(e.id, shirt, idx, leader, leader ? 0x232a3d : 0x2e3a59);
    parts.root.position.set(x, y, z);
    const c: Character = {
      ...parts, id: e.id, name: e.name, kind: e.kind, dept: e.department, color,
      pose: { hipY: 0.5, legX: -Math.PI / 2, torsoX: 0.4, headX: 0.5, headY: 0, armL: -1.2, armR: -1.2 },
      seat: new THREE.Vector3(x, y, z), seatRotY: 0, stand: new THREE.Vector3(x, 0, z - 1.25), station,
      presence: "sleeping", walking: false, carrying: false, handing: false, pop: 0, path: [], onArrive: null, lock: Promise.resolve(),
    };
    this.chars[e.id] = c;
    return c;
  }

  private addOwner(z: number) {
    const parts = this.makeCharacter("owner", 0x20283c, 2, false, 0x151b29);
    parts.root.position.set(0, 0, z); parts.root.rotation.y = Math.PI;
    this.box(1.4, 0.95, 0.7, this.mat(0x3a3350), 0, 0.475, z - 0.9);
    this.box(0.9, 0.08, 0.5, this.mat(0xffd35c, { emissive: 0x3a2c00 }), 0, 0.99, z - 0.9);
    this.chars.owner = {
      ...parts, id: "owner", name: "You", kind: "owner", dept: "owner", color: 0xffd35c,
      pose: { hipY: 0.7, legX: 0, torsoX: 0, headX: 0, headY: 0, armL: 0, armR: 0 },
      seat: new THREE.Vector3(0, 0, z), seatRotY: Math.PI, stand: new THREE.Vector3(0, 0, z),
      station: { deskTop: new THREE.Vector3(0, 1.03, z - 0.9) },
      presence: "owner", walking: false, carrying: false, handing: false, pop: 0, path: [], onArrive: null, lock: Promise.resolve(),
    };
    this.floorText("Your desk", 0, z + 1.1, "#ffd35c", 5);
    this.focusPoints.owner = { target: new THREE.Vector3(0, 0, z - 2), radius: 14 };
  }

  // ================================================================ state
  setPresence(id: string, state: Presence) {
    const c = this.chars[id];
    if (c && id !== "owner") c.presence = state;
  }
  setSpeed(x: number) { this.speed = x; }

  // ================================================================ notes
  private noteMats: Record<number, THREE.Material[]> = {};
  private noteMaterial(color: number) {
    if (!this.noteMats[color]) {
      const cv = document.createElement("canvas"); cv.width = 16; cv.height = 20;
      const g = cv.getContext("2d")!;
      g.fillStyle = "#fff6d8"; g.fillRect(0, 0, 16, 20);
      g.fillStyle = "#" + color.toString(16).padStart(6, "0"); g.fillRect(0, 0, 16, 4);
      g.fillStyle = "#b9ab86"; [8, 11, 14, 17].forEach((y) => g.fillRect(3, y, 10, 1));
      const t = new THREE.CanvasTexture(cv); t.magFilter = THREE.NearestFilter; t.colorSpace = THREE.SRGBColorSpace;
      const side = new THREE.MeshLambertMaterial({ color: 0xfff6d8 });
      this.noteMats[color] = [side, side, new THREE.MeshLambertMaterial({ map: t, emissive: 0x302a10 }), side, side, side];
    }
    return this.noteMats[color];
  }

  hasNote(taskId: string) { return !!this.notes[taskId]; }

  createNote(taskId: string, dept: string, holder: string) {
    if (this.notes[taskId]) return;
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(0.34, 0.03, 0.44), this.noteMaterial(deptColor(dept)));
    mesh.castShadow = true; mesh.userData.taskId = taskId;
    this.scene.add(mesh);
    this.notes[taskId] = { id: taskId, mesh, holder, inHand: false, n: this.noteN++ };
    this.placeNote(taskId, this.chars[holder] ? holder : "owner", false);
  }

  private placeNote(taskId: string, holderId: string, animate: boolean) {
    const note = this.notes[taskId], h = this.chars[holderId];
    if (!note || !h) return Promise.resolve();
    const stack = Object.values(this.notes).filter((n) => n !== note && n.holder === holderId && !n.inHand).length;
    const to = h.station.deskTop.clone().add(new THREE.Vector3(((stack % 3) - 1) * 0.38, stack * 0.002, -0.05 + Math.floor(stack / 3) * 0.1));
    note.holder = holderId; note.inHand = false;
    this.scene.attach(note.mesh);
    if (!animate) { note.mesh.position.copy(to); note.mesh.rotation.set(0, (Math.random() - 0.5) * 0.4, 0); return Promise.resolve(); }
    const from = note.mesh.position.clone();
    return this.tween(450, (k) => { note.mesh.position.lerpVectors(from, to, k); note.mesh.position.y += Math.sin(k * Math.PI) * 0.6; });
  }

  moveNote(taskId: string, holderId: string) { if (this.notes[taskId] && !this.notes[taskId].inHand) this.placeNote(taskId, holderId, false); }

  async removeNote(taskId: string) {
    const note = this.notes[taskId]; if (!note) return;
    delete this.notes[taskId];
    if (this.following === taskId) this.following = null;
    await this.tween(500, (k) => { const s = Math.max(0.01, 1 - k); note.mesh.scale.set(s, s, s); note.mesh.position.y += 0.03; });
    this.scene.remove(note.mesh);
  }

  clearNotes() { Object.values(this.notes).forEach((n) => this.scene.remove(n.mesh)); this.notes = {}; }

  // ================================================================ walking
  private tween(ms: number, step: (k: number) => void) {
    return new Promise<void>((res) => this.tweens.add({ ms, t: 0, step, res }));
  }
  private sleep(ms: number) { return this.tween(ms, () => {}); }

  private route(A: Character, B: Character) {
    const a = A.stand, b = B.stand;
    const w = (p: THREE.Vector3, o: THREE.Vector3) => (p.x < -1 ? -WALK_X : p.x > 1 ? WALK_X : o.x < 0 ? -WALK_X : WALK_X);
    const wa = w(a, b), wb = w(b, a);
    const pts = [a.clone(), new THREE.Vector3(wa, 0, a.z)];
    if (wa !== wb) {
      const mid = (a.z + b.z) / 2;
      const lane = this.crossLanes.reduce((best, z) => (Math.abs(z - mid) < Math.abs(best - mid) ? z : best), this.crossLanes[0]);
      pts.push(new THREE.Vector3(wa, 0, lane), new THREE.Vector3(wb, 0, lane));
    }
    pts.push(new THREE.Vector3(wb, 0, b.z), b.clone());
    return pts.filter((p, i) => i === 0 || p.distanceTo(pts[i - 1]) > 0.01);
  }
  private walkPath(c: Character, pts: THREE.Vector3[]) {
    return new Promise<void>((res) => { c.path = pts.slice(); c.onArrive = res; });
  }
  private async acquire(c: Character) {
    let release!: () => void;
    const prev = c.lock;
    c.lock = new Promise<void>((r) => (release = r));
    await prev;
    return release;
  }

  /** `from` gets up, carries the note to `to`'s desk and walks back. */
  handoff(taskId: string, fromId: string, toId: string) {
    let deliveredRes!: () => void;
    const delivered = new Promise<void>((r) => (deliveredRes = r));
    const returned = (async () => {
      const A = this.chars[fromId], B = this.chars[toId], note = this.notes[taskId];
      if (!A || !B || !note || A === B) { if (note && B) this.placeNote(taskId, toId, false); deliveredRes(); return; }
      const release = await this.acquire(A);
      A.walking = true; this.onWalking(A.id, true);
      await this.sleep(350);
      note.inHand = true; A.carrying = true;
      A.hand.attach(note.mesh);
      const from = note.mesh.position.clone(), grip = new THREE.Vector3(0, -0.05, 0.12);
      await this.tween(250, (k) => note.mesh.position.lerpVectors(from, grip, k));
      note.mesh.rotation.set(0.2, 0, 0);
      if (A.id !== "owner") await this.walkPath(A, [A.stand.clone()]);
      const path = this.route(A, B);
      await this.walkPath(A, path);
      const d = B.station.deskTop;
      A.root.rotation.y = Math.atan2(d.x - A.root.position.x, d.z - A.root.position.z);
      A.handing = true;
      await this.sleep(250);
      A.carrying = false;
      await this.placeNote(taskId, toId, true);
      A.handing = false;
      B.pop = 1;
      deliveredRes();
      await this.walkPath(A, path.slice().reverse());
      if (A.id !== "owner") await this.walkPath(A, [A.seat.clone()]);
      A.root.position.copy(A.seat); A.root.rotation.y = A.seatRotY;
      A.walking = false; this.onWalking(A.id, false);
      release();
    })();
    return { delivered, returned };
  }

  pop(id: string) { const c = this.chars[id]; if (c) c.pop = 1; }

  // ================================================================ poses
  private targetPose(c: Character, t: number): Pose {
    const P: Pose = { hipY: 0.5, legX: -Math.PI / 2, torsoX: 0, headX: 0, headY: 0, armL: -0.35, armR: -0.35 };
    if (c.id === "owner") return { hipY: 0.7, legX: 0, torsoX: 0, headX: 0.12 + Math.sin(t * 0.8) * 0.03, headY: Math.sin(t * 0.4) * 0.25, armL: 0.05, armR: 0.05 };
    switch (c.presence) {
      case "sleeping": case "paused":
        return { ...P, torsoX: 0.55 + Math.sin(t * 1.4) * (c.presence === "paused" ? 0 : 0.03), headX: 0.6, armL: -1.3, armR: -1.3 };
      case "working":
        return { ...P, torsoX: 0.12, headX: 0.1 + Math.sin(t * 5) * 0.03, armL: -1.1 + Math.sin(t * 16) * 0.12, armR: -1.1 + Math.sin(t * 16 + Math.PI) * 0.12 };
      case "supervising":
        return { ...P, headX: -0.05, headY: Math.sin(t * 0.7) * 0.6, armL: -0.4, armR: -0.4 };
      case "waiting_owner":
        return { ...P, torsoX: -0.05, headX: -0.15, armL: -0.3, armR: -2.8 + Math.sin(t * 7) * 0.25 };
      case "blocked":
        return { ...P, torsoX: 0.15, headX: 0.2, armL: -2.5, armR: -2.5 };
    }
    return P;
  }

  private animate(c: Character, t: number, dt: number) {
    let P: Pose, swing = 0;
    if (c.walking) {
      swing = c.path.length ? Math.sin(t * 11) * 0.65 : 0;
      P = { hipY: 0.7, legX: 0, torsoX: 0, headX: 0, headY: 0, armL: -swing * 0.8, armR: c.handing ? -1.6 : c.carrying ? -1.2 : swing * 0.8 };
    } else P = this.targetPose(c, t);
    const k = 1 - Math.exp(-dt * 7), p = c.pose;
    (Object.keys(p) as PoseKey[]).forEach((key) => (p[key] += (P[key] - p[key]) * k));
    c.hips.position.y = p.hipY;
    c.legs[0].rotation.x = p.legX + swing; c.legs[1].rotation.x = p.legX - swing;
    c.torso.rotation.x = p.torsoX;
    c.neck.rotation.x = p.headX; c.neck.rotation.y = p.headY;
    c.arms[0].rotation.x = p.armL; c.arms[1].rotation.x = p.armR;
    const closed = !c.walking && (c.presence === "sleeping" || c.presence === "paused");
    c.eyes.forEach((e) => (e.scale.y = closed ? 0.25 : Math.sin(t * 0.9 + c.seat.x) > 0.985 ? 0.2 : 1));
    const baseY = c.walking ? 0 : c.seat.y;
    if (c.pop > 0) { c.pop = Math.max(0, c.pop - dt * 2.5); c.root.position.y = baseY + Math.sin(c.pop * Math.PI) * 0.18; }
    const st = c.station;
    if (st.screenMat && st.glow) {
      const on = c.presence === "working" && !c.walking;
      if (st.lit !== on) {
        st.screenMat.emissive.setHex(on ? new THREE.Color(c.color).multiplyScalar(0.8).getHex() : 0x000000);
        st.glow.color.setHex(on ? c.color : 0x2b3040);
        st.lit = on;
      }
    }
    if (c.path.length) {
      const target = c.path[0], pos = c.root.position;
      const dx = target.x - pos.x, dz = target.z - pos.z, dist = Math.hypot(dx, dz), step = dt * SPEED * this.speed;
      if (dist > 0.02) c.root.rotation.y = Math.atan2(dx, dz);
      pos.y = 0;
      if (dist <= step) {
        pos.x = target.x; pos.z = target.z; c.path.shift();
        if (!c.path.length && c.onArrive) { const r = c.onArrive; c.onArrive = null; r(); }
      } else { pos.x += (dx / dist) * step; pos.z += (dz / dist) * step; }
    }
  }

  // ================================================================ camera + input
  focus(key: string) {
    const f = this.focusPoints[key]; if (!f) return;
    this.following = null;
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) { this.cam.target.copy(f.target); this.cam.radius = f.radius; }
    else this.camGoal = { target: f.target.clone(), radius: f.radius };
  }
  follow(taskId: string | null) { this.following = taskId; if (taskId) { this.camGoal = null; this.cam.radius = Math.min(this.cam.radius, 20); } }

  private resize = () => {
    const w = this.canvas.clientWidth, h = this.canvas.clientHeight;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / Math.max(1, h);
    this.camera.updateProjectionMatrix();
  };

  private bindInput() {
    const pointers = new Map<number, { x: number; y: number }>();
    let moved = 0, pinch = 0;
    const cv = this.canvas, signal = this.abort.signal;
    cv.addEventListener("pointerdown", (e) => { cv.setPointerCapture(e.pointerId); pointers.set(e.pointerId, { x: e.clientX, y: e.clientY }); moved = 0; }, { signal });
    cv.addEventListener("pointermove", (e) => {
      if (!pointers.has(e.pointerId)) {
        const p = this.pick(e);
        cv.classList.toggle("hover", !!p);
        const h = p?.emp ?? null;
        if (h !== this.hovered) { this.hovered = h; this.onHover(h); }
        return;
      }
      const prev = pointers.get(e.pointerId)!, dx = e.clientX - prev.x, dy = e.clientY - prev.y;
      pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (pointers.size === 2) {
        const [a, b] = [...pointers.values()], d = Math.hypot(a.x - b.x, a.y - b.y);
        if (pinch) this.cam.radius = THREE.MathUtils.clamp(this.cam.radius * (pinch / d), 10, 70);
        pinch = d; moved += 10; return;
      }
      moved += Math.abs(dx) + Math.abs(dy);
      if (moved > 4) {
        this.camGoal = null; this.following = null;
        this.cam.theta -= dx * 0.005;
        this.cam.phi = THREE.MathUtils.clamp(this.cam.phi - dy * 0.004, 0.35, 1.35);
      }
    }, { signal });
    const end = (e: PointerEvent) => {
      const was = pointers.delete(e.pointerId); pinch = 0;
      if (was && moved <= 4 && e.type === "pointerup") {
        const p = this.pick(e);
        if (p?.focus) { this.focus(p.focus); this.onFocus(p.focus); }
        else if (p) this.onPick(p);
      }
    };
    cv.addEventListener("pointerup", end, { signal });
    cv.addEventListener("pointercancel", end, { signal });
    cv.addEventListener("wheel", (e) => {
      e.preventDefault(); this.camGoal = null;
      this.cam.radius = THREE.MathUtils.clamp(this.cam.radius * (1 + e.deltaY * 0.0012), 10, 70);
    }, { passive: false, signal });
  }

  private ray = new THREE.Raycaster();
  private pick(e: PointerEvent): { emp?: string; task?: string; focus?: string } | null {
    const r = this.canvas.getBoundingClientRect();
    const ndc = new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    this.ray.setFromCamera(ndc, this.camera);
    const n = this.ray.intersectObjects(Object.values(this.notes).map((x) => x.mesh), false)[0];
    if (n) return { task: n.object.userData.taskId };
    const hit = this.ray.intersectObjects(this.pickables, false)[0];
    const emp = hit?.object.userData.empId;
    if (emp && emp !== "owner") return { emp };
    const rug = this.ray.intersectObjects(this.rugs, false)[0];
    return rug ? { focus: rug.object.userData.focusKey } : null;
  }

  private updateCamera(dt: number) {
    if (this.camGoal) {
      const k = 1 - Math.exp(-dt * 4);
      this.cam.target.lerp(this.camGoal.target, k);
      this.cam.radius += (this.camGoal.radius - this.cam.radius) * k;
      if (this.cam.target.distanceTo(this.camGoal.target) < 0.02) this.camGoal = null;
    }
    if (this.following && this.notes[this.following]) {
      const wp = new THREE.Vector3(); this.notes[this.following].mesh.getWorldPosition(wp); wp.y = 0;
      this.cam.target.lerp(wp, 1 - Math.exp(-dt * 3));
    }
    const { target: T, radius: r, theta, phi } = this.cam;
    this.camera.position.set(T.x + r * Math.sin(phi) * Math.sin(theta), T.y + r * Math.cos(phi), T.z + r * Math.sin(phi) * Math.cos(theta));
    this.camera.lookAt(T);
  }

  // ================================================================ loop
  private tmp = new THREE.Vector3();
  private project(world: THREE.Vector3, yOff: number, key: string) {
    this.tmp.copy(world); this.tmp.y += yOff; this.tmp.project(this.camera);
    const vis = this.tmp.z < 1;
    this.labelSink(key, (this.tmp.x * 0.5 + 0.5) * this.canvas.clientWidth, (-this.tmp.y * 0.5 + 0.5) * this.canvas.clientHeight, vis);
  }

  private frame = (now: number) => {
    const dt = Math.min(0.05, (now - this.last) / 1000);
    this.last = now; this.clock += dt;
    for (const tw of [...this.tweens]) {
      tw.t += dt * 1000 * this.speed;
      const k = Math.min(1, tw.t / tw.ms), e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
      tw.step(e);
      if (k >= 1) { this.tweens.delete(tw); tw.res(); }
    }
    for (const c of Object.values(this.chars)) this.animate(c, this.clock, dt);
    for (const n of Object.values(this.notes)) if (!n.inHand) n.mesh.position.y += Math.sin(this.clock * 3 + n.n) * 0.0006;
    this.updateCamera(dt);
    this.renderer.render(this.scene, this.camera);
    for (const c of Object.values(this.chars)) { c.head.getWorldPosition(this.tmp); this.project(this.tmp.clone(), 0.55, c.id); }
    for (const s of this.signs) this.project(s.pos, 0, s.key);
    this.raf = requestAnimationFrame(this.frame);
  };
}
