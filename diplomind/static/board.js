import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { SVGLoader } from "three/addons/loaders/SVGLoader.js";
import { COLORS, escapeHTML as esc, provinceKey } from "./rules.js";

const SCALE = 30 / 1835;
const assets = new Map();
const tint = (color, white = 0.68) =>
  new THREE.Color(color).lerp(new THREE.Color("#ececd7"), white);
export class StrategyBoard {
  constructor(host, { onSelect, onHover, onMode, onError } = {}) {
    this.host = host;
    this.onSelect = onSelect;
    this.onHover = onHover;
    this.onMode = onMode;
    this.onError = onError;
    this.mode = "3d";
    this.selected = null;
    this.draft = {};
    this.data = null;
    this.disposed = false;
    this.ready = false;
    this.raycaster = new THREE.Raycaster();
    this.pointer = new THREE.Vector2();
    this.hitObjects = [];
    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(host);
  }
  async init() {
    try {
      const canvas = document.createElement("canvas");
      const context = canvas.getContext("webgl2", {
        alpha: true,
        antialias: true,
        powerPreference: "high-performance",
      });
      if (!context) {
        this.mode = "2d";
        this.onMode?.("2d", false);
        this.onError?.("This browser is using the fully playable 2D board.");
        if (this.data) this.build2D();
        return;
      }
      this.renderer = new THREE.WebGLRenderer({
        canvas,
        context,
        antialias: true,
        alpha: true,
        powerPreference: "high-performance",
      });
      this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      this.renderer.setClearColor(0xdfe9df, 0);
      this.renderer.shadowMap.enabled = true;
      this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
      this.renderer.outputColorSpace = THREE.SRGBColorSpace;
      this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
      this.renderer.toneMappingExposure = 0.96;
      this.renderer.domElement.setAttribute(
        "aria-label",
        "3D strategy board. Select your units using the command desk for keyboard controls.",
      );
      this.host.replaceChildren(this.renderer.domElement);
      this.scene = new THREE.Scene();
      this.camera = new THREE.OrthographicCamera(-18, 18, 13, -13, 0.1, 150);
      this.controls = new OrbitControls(this.camera, this.renderer.domElement);
      this.controls.enableDamping = true;
      this.controls.dampingFactor = 0.12;
      this.controls.maxPolarAngle = Math.PI * 0.47;
      this.controls.minPolarAngle = 0.18;
      this.controls.minZoom = 0.65;
      this.controls.maxZoom = 3.7;
      this.controls.enablePan = true;
      this.controls.mouseButtons = {
        LEFT: THREE.MOUSE.PAN,
        MIDDLE: THREE.MOUSE.DOLLY,
        RIGHT: THREE.MOUSE.ROTATE,
      };
      this.controls.touches = {
        ONE: THREE.TOUCH.PAN,
        TWO: THREE.TOUCH.DOLLY_ROTATE,
      };
      this.reset();
      this.scene.add(new THREE.HemisphereLight(0xf8fff1, 0x78857a, 1.6));
      const sun = new THREE.DirectionalLight(0xfff1d2, 2.3);
      sun.position.set(-12, 24, 12);
      sun.castShadow = true;
      sun.shadow.mapSize.set(2048, 2048);
      sun.shadow.camera.left = -22;
      sun.shadow.camera.right = 22;
      sun.shadow.camera.top = 20;
      sun.shadow.camera.bottom = -20;
      sun.shadow.normalBias = 0.02;
      sun.shadow.bias = -0.0001;
      this.scene.add(sun);
      const fill = new THREE.DirectionalLight(0x9cc6cc, 0.85);
      fill.position.set(16, 16, -15);
      this.scene.add(fill);
      this.boardGroup = new THREE.Group();
      this.unitsGroup = new THREE.Group();
      this.labelGroup = new THREE.Group();
      this.arrowGroup = new THREE.Group();
      this.scene.add(
        this.boardGroup,
        this.unitsGroup,
        this.labelGroup,
        this.arrowGroup,
      );
      this.bindPointer();
      this.resize();
      this.ready = true;
      this.dirty = true;
      this.controls.addEventListener("change", () => {
        this.dirty = true;
      });
      const animate = () => {
        if (this.disposed) return;
        this.frame = requestAnimationFrame(animate);
        if (this.mode === "3d" && !document.hidden) {
          const changed = this.controls.update();
          if (this.dirty || changed) {
            this.renderer.render(this.scene, this.camera);
            this.dirty = false;
          }
        }
      };
      animate();
      this.renderer.domElement.addEventListener("webglcontextlost", (event) => {
        event.preventDefault();
        this.ready = false;
        this.setMode("2d");
        this.onError?.(
          "3D rendering was interrupted. The 2D board is ready to play.",
        );
      });
      await this.loadAssets();
      if (this.data) this.build3D();
    } catch (error) {
      this.mode = "2d";
      this.ready = false;
      this.onMode?.("2d", false);
      this.onError?.("This browser is using the fully playable 2D board.");
      if (this.data) this.build2D();
    }
  }
  async loadAssets() {
    const loader = new GLTFLoader();
    await Promise.all(
      ["army", "fleet", "center", "board-prop"].map(async (name) => {
        try {
          const gltf = await loader.loadAsync(`/static/assets/${name}.glb`);
          assets.set(name, gltf.scene);
        } catch (error) {
          this.onError?.(
            `The ${name} miniature could not load. A simple piece is shown instead.`,
          );
        }
      }),
    );
    this.host.dataset.assetsLoaded = String(assets.size);
  }
  point(x, y, height = 0.3) {
    return new THREE.Vector3(
      (x - this.data.width / 2) * SCALE,
      height,
      (y - this.data.height / 2) * SCALE,
    );
  }
  setData(data) {
    this.data = data;
    this.names = Object.fromEntries(data.provinces.map((p) => [p.id, p.name]));
    if (this.mode === "2d") this.build2D();
    else if (this.ready) this.build3D();
  }
  disposeGroup(group) {
    if (!group) return;
    while (group.children.length) {
      const item = group.children[0];
      group.remove(item);
      item.traverse((child) => {
        if (child.userData.ownedGeometry) child.geometry?.dispose();
        if (child.userData.ownedMaterial) {
          const mats = Array.isArray(child.material)
            ? child.material
            : [child.material];
          mats.filter(Boolean).forEach((m) => {
            if (m.map) m.map.dispose();
            m.dispose();
          });
        }
      });
    }
  }
  own(mesh) {
    mesh.userData.ownedGeometry = true;
    mesh.userData.ownedMaterial = true;
    return mesh;
  }
  build3D() {
    this.dirty = true;
    if (!this.ready || !this.data) return;
    this.disposeGroup(this.boardGroup);
    this.disposeGroup(this.unitsGroup);
    this.disposeGroup(this.labelGroup);
    this.hitObjects = [];
    this.provinceMeshes = new Map();
    const w = this.data.width * SCALE,
      h = this.data.height * SCALE;
    const slab = this.own(
      new THREE.Mesh(
        new THREE.BoxGeometry(w + 0.7, 0.4, h + 0.7),
        new THREE.MeshStandardMaterial({ color: "#274941", roughness: 0.68 }),
      ),
    );
    slab.position.y = -0.25;
    slab.receiveShadow = true;
    this.boardGroup.add(slab);
    const trim = this.own(
      new THREE.Mesh(
        new THREE.BoxGeometry(w + 0.55, 0.07, h + 0.55),
        new THREE.MeshStandardMaterial({
          color: "#baa568",
          roughness: 0.52,
          metalness: 0.2,
        }),
      ),
    );
    trim.position.y = -0.04;
    this.boardGroup.add(trim);
    const ocean = this.own(
      new THREE.Mesh(
        new THREE.BoxGeometry(w, 0.12, h),
        new THREE.MeshStandardMaterial({
          color: "#8bb7b0",
          roughness: 0.72,
          metalness: 0.05,
        }),
      ),
    );
    ocean.position.y = 0.045;
    ocean.receiveShadow = true;
    this.boardGroup.add(ocean);
    const loader = new SVGLoader();
    for (const p of this.data.provinces) {
      const water = p.type === "WATER",
        impassable = p.type === "SHUT";
      const col = water
        ? "#93beb6"
        : impassable
          ? "#c1c2ae"
          : p.influence || p.owner
            ? tint(COLORS[p.influence || p.owner] || "#b2b7a4", 0.47)
            : new THREE.Color("#dbdcc1");
      const [tx, ty] = p.path_transform || [0, 0];
      let paths;
      try {
        paths = loader.parse(
          `<svg xmlns="http://www.w3.org/2000/svg"><g transform="translate(${tx} ${ty})">${p.paths.map((d) => `<path d="${esc(d)}"/>`).join("")}</g></svg>`,
        ).paths;
      } catch (error) {
        continue;
      }
      const meshes = [];
      for (const path of paths)
        for (const shape of SVGLoader.createShapes(path)) {
          const geometry = new THREE.ExtrudeGeometry(shape, {
            depth: water ? 2 : 22,
            bevelEnabled: false,
            curveSegments: 2,
          });
          geometry.rotateX(Math.PI / 2);
          geometry.scale(SCALE, SCALE, SCALE);
          geometry.translate(-w / 2, water ? 0.125 : 0.47, -h / 2);
          const mesh = this.own(
            new THREE.Mesh(
              geometry,
              new THREE.MeshStandardMaterial({
                color: col,
                roughness: water ? 0.83 : 0.9,
                metalness: 0,
                emissive: 0x000000,
              }),
            ),
          );
          mesh.receiveShadow = true;
          mesh.castShadow = !water;
          mesh.userData.province = p.id;
          mesh.userData.baseColor = mesh.material.color.clone();
          this.boardGroup.add(mesh);
          this.hitObjects.push(mesh);
          meshes.push(mesh);
          const edge = this.own(
            new THREE.LineSegments(
              new THREE.EdgesGeometry(geometry, 30),
              new THREE.LineBasicMaterial({
                color: water ? "#608d81" : "#627652",
                transparent: true,
                opacity: water ? 0.42 : 0.6,
              }),
            ),
          );
          this.boardGroup.add(edge);
        }
      this.provinceMeshes.set(p.id, meshes);
      if (p.center && p.center_position) {
        const c = this.model("center", COLORS[p.owner] || "#b79e5c");
        c.position.copy(
          this.point(p.center_position.x, p.center_position.y, 0.49),
        );
        c.scale.setScalar(0.23);
        this.boardGroup.add(c);
      }
      const label = this.makeLabel(p.id, water);
      label.position.copy(
        this.point(p.x, p.y + (water ? 0 : 31), water ? 0.17 : 0.58),
      );
      this.labelGroup.add(label);
    }
    for (const u of this.data.units) {
      const unit = this.model(
        u.type === "A" ? "army" : "fleet",
        COLORS[u.power],
      );
      const size = u.type === "A" ? 0.82 : 1.03;
      unit.scale.setScalar(size);
      unit.position.copy(this.point(u.x, u.y, 0.53));
      unit.rotation.y = u.type === "F" ? Math.PI * 0.28 : 0;
      unit.userData.unit = u;
      unit.traverse((child) => {
        if (child.isMesh) {
          child.userData.unit = u;
          child.castShadow = true;
          this.hitObjects.push(child);
        }
      });
      this.unitsGroup.add(unit);
      const ring = this.own(
        new THREE.Mesh(
          new THREE.RingGeometry(0.44, 0.49, 40),
          new THREE.MeshBasicMaterial({
            color: COLORS[u.power],
            transparent: true,
            opacity: u.dislodged ? 0.4 : 0.85,
            side: THREE.DoubleSide,
          }),
        ),
      );
      ring.rotation.x = -Math.PI / 2;
      ring.position.copy(this.point(u.x, u.y, 0.49));
      ring.userData.ringLocation = provinceKey(u.location);
      this.unitsGroup.add(ring);
    }
    const prop = this.model("board-prop", "#baa568");
    prop.scale.setScalar(1.25);
    prop.position.set(-w / 2 + 1.4, 0.3, h / 2 - 1.4);
    this.boardGroup.add(prop);
    this.setSelection(this.selected);
    this.setDraft(this.draft);
    this.host.dataset.renderer = "3d";
    this.host.dataset.provinces = String(this.data.provinces.length);
    this.resize();
  }
  model(name, color) {
    const source = assets.get(name);
    if (source) {
      const clone = source.clone(true);
      clone.traverse((child) => {
        if (!child.isMesh) return;
        const mats = Array.isArray(child.material)
          ? child.material
          : [child.material];
        const copies = mats.map((material) => {
          const m = material.clone();
          if (m.name === "Nation" || m.name.startsWith("Nation.")) {
            m.color.set(color || "#aba97f");
            m.metalness = 0.16;
            m.roughness = 0.48;
          }
          return m;
        });
        child.material = Array.isArray(child.material) ? copies : copies[0];
        child.userData.ownedMaterial = true;
        child.castShadow = true;
        child.receiveShadow = true;
      });
      return clone;
    }
    return this.own(
      new THREE.Mesh(
        name === "fleet"
          ? new THREE.ConeGeometry(0.32, 0.45, 4)
          : new THREE.CylinderGeometry(0.25, 0.33, 0.45, 12),
        new THREE.MeshStandardMaterial({
          color: color || "#ae9b64",
          roughness: 0.7,
        }),
      ),
    );
  }
  makeLabel(text, sea) {
    const canvas = document.createElement("canvas");
    canvas.width = 128;
    canvas.height = 64;
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, 128, 64);
    ctx.font = `${sea ? "400" : "600"} 28px Arial`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillStyle = sea ? "#386556" : "#233e2b";
    if (!sea) {
      ctx.strokeStyle = "#e9edd6";
      ctx.lineWidth = 4;
      ctx.strokeText(text, 64, 32);
    }
    ctx.fillText(text, 64, 32);
    const texture = new THREE.CanvasTexture(canvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    const sprite = new THREE.Sprite(
      new THREE.SpriteMaterial({
        map: texture,
        transparent: true,
        depthWrite: false,
        depthTest: false,
        opacity: sea ? 0.88 : 1,
        toneMapped: false,
      }),
    );
    sprite.scale.set(sea ? 1.7 : 1.25, sea ? 0.85 : 0.625, 1);
    sprite.userData.ownedMaterial = true;
    return sprite;
  }
  bindPointer() {
    const canvas = this.renderer.domElement;
    let down;
    canvas.addEventListener("pointerdown", (e) => {
      down = { x: e.clientX, y: e.clientY };
    });
    canvas.addEventListener("pointerup", (e) => {
      if (
        !down ||
        Math.hypot(e.clientX - down.x, e.clientY - down.y) > 6 ||
        e.button !== 0
      )
        return;
      const hit = this.pick(e);
      if (hit) this.onSelect?.(hit);
    });
    canvas.addEventListener("pointermove", (e) => {
      const hit = this.pick(e);
      canvas.style.cursor = hit ? "pointer" : "grab";
      this.onHover?.(hit);
    });
    canvas.addEventListener("pointerleave", () => this.onHover?.(null));
  }
  pick(event) {
    if (!this.data) return null;
    const r = this.renderer.domElement.getBoundingClientRect();
    this.pointer.set(
      ((event.clientX - r.left) / r.width) * 2 - 1,
      (-(event.clientY - r.top) / r.height) * 2 + 1,
    );
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const hits = this.raycaster.intersectObjects(this.hitObjects, false);
    for (const hit of hits) {
      const { unit, province } = hit.object.userData;
      if (unit) return { province: provinceKey(unit.location), unit };
      if (province) return { province };
    }
    return null;
  }
  setSelection(key) {
    this.dirty = true;
    this.selected = key ? provinceKey(key) : null;
    if (this.mode === "2d") {
      this.host
        .querySelectorAll("[data-province]")
        .forEach((el) =>
          el.classList.toggle(
            "selected",
            el.dataset.province === this.selected,
          ),
        );
      return;
    }
    for (const [loc, meshes] of this.provinceMeshes || [])
      for (const m of meshes) {
        m.material.color.copy(m.userData.baseColor);
        m.material.emissive.setHex(loc === this.selected ? 0x38410b : 0x000000);
      }
    this.unitsGroup?.children.forEach((c) => {
      if (c.userData.ringLocation)
        c.material.color.set(
          c.userData.ringLocation === this.selected
            ? "#fff2a5"
            : COLORS[
                this.data.units.find(
                  (u) => provinceKey(u.location) === c.userData.ringLocation,
                )?.power
              ] || "#bba667",
        );
    });
  }
  setDraft(draft) {
    this.dirty = true;
    this.draft = draft || {};
    if (this.mode === "2d") {
      this.draw2DArrows();
      return;
    }
    this.disposeGroup(this.arrowGroup);
    if (!this.data) return;
    for (const order of Object.values(this.draft)) {
      const p = order.split(" ");
      if (!["-", "R", "S", "C"].includes(p[2])) continue;
      const from =
        this.data.locations[p[1]] || this.data.locations[provinceKey(p[1])];
      const target = ["-", "R"].includes(p[2]) ? p[3] : p[6] || p[4];
      const to =
        this.data.locations[target] || this.data.locations[provinceKey(target)];
      if (!from || !to) continue;
      const a = this.point(from.x, from.y, 0.8),
        b = this.point(to.x, to.y, 0.8),
        mid = a.clone().lerp(b, 0.5);
      mid.y += 0.45;
      const curve = new THREE.QuadraticBezierCurve3(a, mid, b);
      const line = this.own(
        new THREE.Mesh(
          new THREE.TubeGeometry(curve, 20, 0.035, 6, false),
          new THREE.MeshBasicMaterial({
            color: p[2] === "S" ? "#718d38" : "#b08435",
            transparent: true,
            opacity: 0.9,
          }),
        ),
      );
      this.arrowGroup.add(line);
      const tip = this.own(
        new THREE.Mesh(
          new THREE.ConeGeometry(0.13, 0.35, 8),
          new THREE.MeshBasicMaterial({ color: "#aa7b28" }),
        ),
      );
      tip.position.copy(b);
      tip.quaternion.setFromUnitVectors(
        new THREE.Vector3(0, 1, 0),
        curve.getTangent(1).normalize(),
      );
      this.arrowGroup.add(tip);
    }
  }
  build2D() {
    if (!this.data) return;
    this.host.style.touchAction = "pan-y";
    const d = this.data;
    this.host.innerHTML = `<svg class="board-fallback" role="img" aria-label="Interactive 2D strategy map of Europe" viewBox="-35 -20 ${d.width + 70} ${d.height + 40}"><defs><marker id="arrowhead" markerWidth="7" markerHeight="7" refX="5" refY="3" orient="auto"><path d="M0,0 L0,6 L6,3 z" fill="#a7792d"/></marker></defs><rect x="0" y="0" width="${d.width}" height="${d.height}" fill="#aacdc0"/>${d.provinces.map((p) => `<g class="province" data-province="${p.id}">${p.paths.map((path) => `<path d="${esc(path)}" transform="translate(${(p.path_transform || [0, 0]).join(" ")})" fill="${p.type === "WATER" ? "#aad0c2" : p.type === "SHUT" ? "#c1c6ae" : p.influence || p.owner ? "#" + tint(COLORS[p.influence || p.owner] || "#b1b5a0", 0.6).getHexString() : "#dfe4c6"}"/>`).join("")}<title>${esc(p.name)}</title></g>`).join("")}${d.provinces
      .filter((p) => p.center && p.center_position)
      .map(
        (p) =>
          `<circle cx="${p.center_position.x}" cy="${p.center_position.y}" r="7" stroke="#eff3d8" stroke-width="3" fill="${COLORS[p.owner] || "#ae954c"}"/>`,
      )
      .join(
        "",
      )}<g id="draft-arrows"></g>${d.provinces.map((p) => `<text class="board-label ${p.type === "WATER" ? "sea-label" : ""}" x="${p.x}" y="${p.y + 34}" text-anchor="middle">${p.id}</text>`).join("")}${d.units.map((u) => `<g class="unit" data-province="${provinceKey(u.location)}" data-unit="${esc(u.location)}" transform="translate(${u.x} ${u.y})"><circle class="unit-base" r="19" fill="${COLORS[u.power]}" stroke="#f4f6df" stroke-width="2"/><text text-anchor="middle" dominant-baseline="central">${u.type === "A" ? "▲" : "▰"}</text><title>${esc(u.power + " " + u.type + " " + u.location)}</title></g>`).join("")}</svg>`;
    this.host.dataset.renderer = "2d";
    this.host.querySelectorAll("[data-province]").forEach((el) => {
      el.addEventListener("click", () => {
        const unit = el.dataset.unit
          ? d.units.find((u) => u.location === el.dataset.unit)
          : undefined;
        this.onSelect?.({ province: el.dataset.province, unit });
      });
      el.addEventListener("pointerenter", () =>
        this.onHover?.({ province: el.dataset.province }),
      );
      el.addEventListener("pointerleave", () => this.onHover?.(null));
    });
    this.setSelection(this.selected);
    this.draw2DArrows();
  }
  draw2DArrows() {
    const group = this.host.querySelector("#draft-arrows");
    if (!group || !this.data) return;
    group.innerHTML = Object.values(this.draft)
      .map((order) => {
        const p = order.split(" ");
        if (!["-", "R", "S", "C"].includes(p[2])) return "";
        const from =
            this.data.locations[p[1]] || this.data.locations[provinceKey(p[1])],
          target = ["-", "R"].includes(p[2]) ? p[3] : p[6] || p[4],
          to =
            this.data.locations[target] ||
            this.data.locations[provinceKey(target)];
        return from && to
          ? `<path d="M${from.x} ${from.y} Q${(from.x + to.x) / 2 + 25} ${(from.y + to.y) / 2 - 30} ${to.x} ${to.y}" stroke="#a7792d" stroke-width="4" fill="none" marker-end="url(#arrowhead)" pointer-events="none"/>`
          : "";
      })
      .join("");
  }
  setMode(mode) {
    this.host.style.touchAction = mode === "2d" ? "pan-y" : "none";
    if (mode === "3d" && !this.ready) {
      this.onError?.(
        "3D is unavailable in this browser. You can play every move in 2D.",
      );
      return;
    }
    this.mode = mode;
    if (mode === "2d") this.build2D();
    else {
      this.host.replaceChildren(this.renderer.domElement);
      this.build3D();
      this.resize();
    }
    this.onMode?.(mode, this.ready);
  }
  resize() {
    this.dirty = true;
    if (!this.ready || !this.renderer) return;
    const { width, height } = this.host.getBoundingClientRect();
    if (!width || !height) return;
    const aspect = width / height;
    const halfHeight = Math.max(12.4, 17.2 / aspect);
    this.camera.left = -halfHeight * aspect;
    this.camera.right = halfHeight * aspect;
    this.camera.top = halfHeight;
    this.camera.bottom = -halfHeight;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height);
  }
  reset() {
    if (!this.camera) return;
    this.camera.position.set(0, 28, 23);
    this.camera.zoom = 1;
    this.camera.lookAt(0, 0, 0);
    this.controls.target.set(0, 0, 0);
    this.camera.updateProjectionMatrix();
    this.controls.update();
  }
  zoom(amount) {
    if (this.mode === "3d" && this.camera) {
      this.camera.zoom = THREE.MathUtils.clamp(
        this.camera.zoom * amount,
        0.65,
        3.7,
      );
      this.camera.updateProjectionMatrix();
    } else {
      const svg = this.host.querySelector("svg");
      if (svg) {
        this.svgZoom = THREE.MathUtils.clamp(
          (this.svgZoom || 1) * amount,
          1,
          2.5,
        );
        const w = this.data.width / this.svgZoom,
          h = this.data.height / this.svgZoom;
        svg.setAttribute(
          "viewBox",
          `${(this.data.width - w) / 2} ${(this.data.height - h) / 2} ${w} ${h}`,
        );
      }
    }
  }
  dispose() {
    this.disposed = true;
    cancelAnimationFrame(this.frame);
    this.resizeObserver.disconnect();
    this.controls?.dispose();
    this.renderer?.dispose();
  }
}
