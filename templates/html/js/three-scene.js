// Сцена 2: поле столбиков three.js с тенями. set(t) выставляет всё по времени — ни часов, ни physics-step.
import * as THREE from 'three';
import { P, E, lerp } from './util.js';

const N = 7, STEP = 1.3, SIZE = .72;                 // сетка N×N столбиков
const BEATS = [3.0, 3.5, 4.0];                       // доли, на которых от центра идёт волна (tick в timeline.json)

export function makeThree(canvas, W, H, accent) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true, alpha: true });
  renderer.setPixelRatio(1); renderer.setSize(W, H, false);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.05;
  renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0d0e11);
  scene.fog = new THREE.Fog(0x0d0e11, 30, 60);
  const cam = new THREE.PerspectiveCamera(30, W / H, .1, 100);

  scene.add(new THREE.HemisphereLight(0xdfe6ff, 0x1a1410, .55));
  const sun = new THREE.DirectionalLight(0xfff1e0, 2.6);
  sun.position.set(-10, 9, 4); sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048); sun.shadow.bias = -.0004; sun.shadow.normalBias = .02; sun.shadow.radius = 3;
  Object.assign(sun.shadow.camera, { left: -10, right: 10, top: 10, bottom: -10, near: 1, far: 45 });
  scene.add(sun);
  const rim = new THREE.PointLight(accent, 30, 14, 1.6); rim.position.set(0, 2.5, 0); scene.add(rim);

  const floor = new THREE.Mesh(new THREE.PlaneGeometry(80, 80), new THREE.MeshStandardMaterial({ color: 0x1d1e23, roughness: .9 }));
  floor.rotation.x = -Math.PI / 2; floor.receiveShadow = true; scene.add(floor);

  const geo = new THREE.BoxGeometry(SIZE, 1, SIZE); geo.translate(0, .5, 0);   // растёт вверх от пола
  const matInk = new THREE.MeshStandardMaterial({ color: 0xe9e5dc, roughness: .55, metalness: 0 });
  const matAcc = new THREE.MeshStandardMaterial({ color: accent, roughness: .4, emissive: accent, emissiveIntensity: .25 });
  const bars = [];
  for (let i = 0; i < N; i++) for (let j = 0; j < N; j++) {
    const x = (i - (N - 1) / 2) * STEP, z = (j - (N - 1) / 2) * STEP, d = Math.hypot(x, z);
    const m = new THREE.Mesh(geo, d < .1 ? matAcc : matInk);
    m.position.set(x, 0, z); m.castShadow = m.receiveShadow = true;
    scene.add(m); bars.push({ m, d, ph: (i * 7 + j * 3) % 5 * .35 });
  }

  function set(t) {
    // вход: камера опускается сверху (2,0 → 2,7 с); выход: быстрый наезд под whoosh (4,25 → 4,5 с)
    const u = t - 2.0;
    const drop = E.outExpo(P(t, 2.0, .7)), push = E.inExpo(P(t, 4.25, .25));
    const ang = .78 + .16 * u, el = lerp(1.25, .62, drop), dist = lerp(40, 33, drop) * (1 - .55 * push);
    cam.position.set(Math.sin(ang) * Math.cos(el) * dist, Math.sin(el) * dist, Math.cos(ang) * Math.cos(el) * dist);
    cam.lookAt(0, lerp(-.6, -1.4, drop), 0);        // цель ниже центра — поле выше подписи
    cam.updateProjectionMatrix();

    for (const b of bars) {
      // медленная волна + импульсы от центра на долях
      let h = .35 + .9 * (.5 + .5 * Math.sin(b.d * 1.15 - u * 3.2 + b.ph));
      for (const tb of BEATS) {
        const r = (t - tb) * 11;                       // радиус фронта, ед./с
        if (r > 0) h += 1.6 * Math.exp(-((b.d - r) ** 2) * 1.4) * Math.exp(-(t - tb) * 2.2);
      }
      if (b.d < .1) h = 1.6 + .9 * Math.max(0, ...BEATS.map(tb => t >= tb ? Math.exp(-(t - tb) * 7) : 0)) + .3 * Math.sin(u * 3);
      b.m.scale.set(1, Math.max(.05, h * E.outQuint(P(t, 2.0 + b.d * .04, .6))), 1);
    }
    rim.intensity = 30 + 40 * Math.max(0, ...BEATS.map(tb => t >= tb ? Math.exp(-(t - tb) * 6) : 0));
  }

  return {
    draw(t) { set(t); renderer.render(scene, cam); },
    clear() { renderer.setClearColor(0x000000, 0); renderer.clear(); }
  };
}
