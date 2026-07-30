/** WebGL2 tiled float image renderer (R32F + LUT).
 * Image coords: FITS array space (origin bottom-left, y north).
 */

import { getColormapLUT } from './colormaps';
import { TILE_SIZE } from './TileCache';

const VERT = `#version 300 es
in vec2 a_pos;
in vec2 a_uv;
out vec2 v_uv;
void main() {
  v_uv = a_uv;
  gl_Position = vec4(a_pos, 0.0, 1.0);
}`;

const FRAG = `#version 300 es
precision highp float;
uniform sampler2D u_image;
uniform sampler2D u_lut;
uniform float u_vmin;
uniform float u_vmax;
uniform int u_stretch;
in vec2 v_uv;
out vec4 outColor;

float stretch(float t) {
  t = clamp(t, 0.0, 1.0);
  if (u_stretch == 1) return t;
  if (u_stretch == 2) return log(1.0 + 9.0 * t) / log(10.0);
  if (u_stretch == 3) return sqrt(t);
  float a = 0.1;
  return asinh(t / a) / asinh(1.0 / a);
}

void main() {
  float v = texture(u_image, v_uv).r;
  if (isnan(v)) { outColor = vec4(0.0, 0.0, 0.0, 0.0); return; }
  float t = (v - u_vmin) / max(u_vmax - u_vmin, 1e-12);
  t = stretch(t);
  outColor = texture(u_lut, vec2(t, 0.5));
}`;

function compile(gl, type, src) {
  const s = gl.createShader(type);
  gl.shaderSource(s, src);
  gl.compileShader(s);
  if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
    const msg = gl.getShaderInfoLog(s);
    gl.deleteShader(s);
    throw new Error(msg);
  }
  return s;
}

export class Renderer {
  constructor(canvas) {
    this.canvas = canvas;
    this.gl = canvas.getContext('webgl2', {
      premultipliedAlpha: false,
      antialias: false,
      alpha: true,
    });
    if (!this.gl) throw new Error('WebGL2 not available');
    this._tiles = new Map();
    this._hasFloatLinear = !!this.gl.getExtension('OES_texture_float_linear');
    this._init();
    this.imgW = 0;
    this.imgH = 0;
  }

  _init() {
    const gl = this.gl;
    const vs = compile(gl, gl.VERTEX_SHADER, VERT);
    const fs = compile(gl, gl.FRAGMENT_SHADER, FRAG);
    const prog = gl.createProgram();
    gl.attachShader(prog, vs);
    gl.attachShader(prog, fs);
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
      throw new Error(gl.getProgramInfoLog(prog));
    }
    this.prog = prog;
    gl.useProgram(prog);

    this._buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, this._buf);
    this.aPos = gl.getAttribLocation(prog, 'a_pos');
    this.aUv = gl.getAttribLocation(prog, 'a_uv');
    gl.enableVertexAttribArray(this.aPos);
    gl.enableVertexAttribArray(this.aUv);

    this.uVmin = gl.getUniformLocation(prog, 'u_vmin');
    this.uVmax = gl.getUniformLocation(prog, 'u_vmax');
    this.uStretch = gl.getUniformLocation(prog, 'u_stretch');
    this.uImage = gl.getUniformLocation(prog, 'u_image');
    this.uLut = gl.getUniformLocation(prog, 'u_lut');

    this.lutTex = gl.createTexture();
    this.setLut('inferno', false);

    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
  }

  setLut(cmap = 'inferno', invert = false) {
    const gl = this.gl;
    const lut = getColormapLUT(cmap, invert);
    gl.bindTexture(gl.TEXTURE_2D, this.lutTex);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 256, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, lut);
  }

  setImageSize(w, h) {
    this.imgW = w;
    this.imgH = h;
  }

  clearTiles() {
    const gl = this.gl;
    for (const [, t] of this._tiles) gl.deleteTexture(t.tex);
    this._tiles.clear();
  }

  clearAll() {
    this.clearTiles();
    if (this._overviewTex) {
      this.gl.deleteTexture(this._overviewTex);
      this._overviewTex = null;
      this._overview = null;
    }
  }

  _texFilter() {
    return this._hasFloatLinear ? this.gl.LINEAR : this.gl.NEAREST;
  }

  uploadTile(z, tx, ty, float32, tw = TILE_SIZE, th = TILE_SIZE) {
    const gl = this.gl;
    const key = `${z}/${tx}/${ty}`;
    let entry = this._tiles.get(key);
    if (!entry) {
      const tex = gl.createTexture();
      entry = { tex, w: tw, h: th };
      this._tiles.set(key, entry);
    }
    gl.bindTexture(gl.TEXTURE_2D, entry.tex);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.R32F, tw, th, 0, gl.RED, gl.FLOAT, float32);
    entry.w = tw;
    entry.h = th;
  }

  uploadOverview(float32, width, height) {
    const gl = this.gl;
    while (gl.getError() !== gl.NO_ERROR) { /* clear */ }
    if (!this._overviewTex) this._overviewTex = gl.createTexture();
    const filter = this._texFilter();
    gl.bindTexture(gl.TEXTURE_2D, this._overviewTex);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, filter);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, filter === gl.LINEAR ? gl.LINEAR : gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.R32F, width, height, 0, gl.RED, gl.FLOAT, float32);
    this._overview = { width, height };
    return { width, height, hasFloatLinear: this._hasFloatLinear };
  }

  resize(cssW, cssH) {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = Math.max(1, Math.floor(cssW * dpr));
    const h = Math.max(1, Math.floor(cssH * dpr));
    if (this.canvas.width !== w || this.canvas.height !== h) {
      this.canvas.width = w;
      this.canvas.height = h;
    }
    this._dpr = dpr;
    this._cssW = cssW;
    this._cssH = cssH;
  }

  /**
   * transform maps display-down pixels → CSS screen.
   * Array coords (iy) are flipped: displayY = imgH - arrayY.
   */
  render({ vmin, vmax, stretch = 'asinh', transform, preferTiles = false }) {
    const gl = this.gl;
    const cssW = this._cssW || this.canvas.clientWidth;
    const cssH = this._cssH || this.canvas.clientHeight;
    this.resize(cssW, cssH);
    const bg = this._clearColor || [0.9, 0.91, 0.93, 1];
    gl.viewport(0, 0, this.canvas.width, this.canvas.height);
    gl.clearColor(bg[0], bg[1], bg[2], bg[3]);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.useProgram(this.prog);

    gl.uniform1f(this.uVmin, vmin);
    gl.uniform1f(this.uVmax, vmax);
    const stretchId = { asinh: 0, linear: 1, log: 2, sqrt: 3 }[stretch] ?? 0;
    gl.uniform1i(this.uStretch, stretchId);

    gl.activeTexture(gl.TEXTURE1);
    gl.bindTexture(gl.TEXTURE_2D, this.lutTex);
    gl.uniform1i(this.uLut, 1);

    const hasTiles = this._tiles.size > 0;
    if (!(preferTiles && hasTiles) && this._overview && this._overviewTex) {
      this._drawQuad(this._overviewTex, 0, 0, this.imgW, this.imgH, transform, cssW, cssH);
    }

    if (hasTiles) {
      for (const [key, entry] of this._tiles) {
        const [zs, txs, tys] = key.split('/');
        const z = Number(zs);
        const tx = Number(txs);
        const ty = Number(tys);
        if (!Number.isFinite(z)) continue;
        const scale = 2 ** z;
        const ix0 = tx * TILE_SIZE * scale;
        const iy0 = ty * TILE_SIZE * scale;
        const ix1 = ix0 + TILE_SIZE * scale;
        const iy1 = iy0 + TILE_SIZE * scale;
        this._drawQuad(entry.tex, ix0, iy0, ix1, iy1, transform, cssW, cssH);
      }
    }
  }

  setClearColor(r, g, b, a = 1) {
    this._clearColor = [r, g, b, a];
  }

  _drawQuad(tex, ix0, iy0, ix1, iy1, transform, cssW, cssH) {
    if (!tex) return;
    const gl = this.gl;
    const { x, y, k } = transform;
    const imgH = this.imgH || 1;
    // Array y: iy0 = south edge, iy1 = north edge → flip to display-down
    const dy0 = imgH - iy1; // top of quad on screen
    const dy1 = imgH - iy0; // bottom of quad on screen
    const sx0 = (ix0 * k + x) / cssW * 2 - 1;
    const sx1 = (ix1 * k + x) / cssW * 2 - 1;
    const syTop = 1 - (dy0 * k + y) / cssH * 2;
    const syBot = 1 - (dy1 * k + y) / cssH * 2;

    // V=0 at south (array row 0) → bottom of screen; V=1 at north → top
    const verts = new Float32Array([
      sx0, syTop, 0, 1,
      sx1, syTop, 1, 1,
      sx0, syBot, 0, 0,
      sx1, syBot, 1, 0,
    ]);
    gl.bindBuffer(gl.ARRAY_BUFFER, this._buf);
    gl.bufferData(gl.ARRAY_BUFFER, verts, gl.STREAM_DRAW);
    gl.vertexAttribPointer(this.aPos, 2, gl.FLOAT, false, 16, 0);
    gl.vertexAttribPointer(this.aUv, 2, gl.FLOAT, false, 16, 8);

    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.uniform1i(this.uImage, 0);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
  }

  destroy() {
    this.clearAll();
  }
}
