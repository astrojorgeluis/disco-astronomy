/** Scientific colormap LUTs as RGBA uint8 arrays (256 entries). */

function lerp(a, b, t) {
  return a + (b - a) * t;
}

function sampleStops(stops, n = 256) {
  const out = new Uint8Array(n * 4);
  for (let i = 0; i < n; i++) {
    const t = i / (n - 1);
    let j = 0;
    while (j < stops.length - 2 && stops[j + 1][0] < t) j++;
    const [t0, c0] = stops[j];
    const [t1, c1] = stops[j + 1];
    const u = (t - t0) / Math.max(t1 - t0, 1e-9);
    out[i * 4] = Math.round(lerp(c0[0], c1[0], u));
    out[i * 4 + 1] = Math.round(lerp(c0[1], c1[1], u));
    out[i * 4 + 2] = Math.round(lerp(c0[2], c1[2], u));
    out[i * 4 + 3] = 255;
  }
  return out;
}

const MAGMA = sampleStops([
  [0, [0, 0, 4]], [0.25, [59, 15, 112]], [0.5, [140, 41, 129]],
  [0.75, [222, 73, 104]], [1, [252, 253, 191]],
]);
const INFERNO = sampleStops([
  [0, [0, 0, 4]], [0.25, [66, 10, 104]], [0.5, [147, 38, 103]],
  [0.75, [221, 81, 58]], [1, [252, 253, 191]],
]);
const VIRIDIS = sampleStops([
  [0, [68, 1, 84]], [0.33, [49, 104, 142]], [0.66, [53, 183, 121]], [1, [253, 231, 37]],
]);
const GRAY = sampleStops([[0, [0, 0, 0]], [1, [255, 255, 255]]]);
const SEISMIC = sampleStops([
  [0, [0, 0, 76]], [0.25, [44, 123, 182]], [0.5, [255, 255, 191]],
  [0.75, [215, 25, 28]], [1, [76, 0, 0]],
]);

const MAPS = {
  magma: MAGMA,
  inferno: INFERNO,
  plasma: sampleStops([
    [0, [13, 8, 135]], [0.25, [126, 3, 168]], [0.5, [204, 71, 120]],
    [0.75, [248, 149, 64]], [1, [240, 249, 33]],
  ]),
  viridis: VIRIDIS,
  gray: GRAY,
  grey: GRAY,
  seismic: SEISMIC,
  jet: sampleStops([
    [0, [0, 0, 127]], [0.2, [0, 0, 255]], [0.4, [0, 255, 255]],
    [0.6, [255, 255, 0]], [0.8, [255, 0, 0]], [1, [127, 0, 0]],
  ]),
  rainbow: sampleStops([
    [0, [128, 0, 255]], [0.2, [0, 0, 255]], [0.4, [0, 255, 255]],
    [0.6, [0, 255, 0]], [0.8, [255, 255, 0]], [1, [255, 0, 0]],
  ]),
};

export function getColormapLUT(name = 'inferno', invert = false) {
  const base = MAPS[name] || MAPS.inferno;
  if (!invert) return base;
  const out = new Uint8Array(base.length);
  for (let i = 0; i < 256; i++) {
    const j = 255 - i;
    out[i * 4] = base[j * 4];
    out[i * 4 + 1] = base[j * 4 + 1];
    out[i * 4 + 2] = base[j * 4 + 2];
    out[i * 4 + 3] = 255;
  }
  return out;
}

export const COLORMAP_NAMES = Object.keys(MAPS);
