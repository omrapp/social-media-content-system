/**
 * Colour-accurate video preview: FFmpeg `eq` + a 3D LUT, applied in WebGL.
 *
 * Why a shader and not a CSS filter — CSS `brightness()` is MULTIPLICATIVE
 * while FFmpeg `eq=brightness` is ADDITIVE in [-1,1], and CSS has no 3D-LUT at
 * all. Previewing with the CSS shorthand would show a different image than the
 * export, which defeats the point of the editor.
 *
 * Formula (mirrors libavfilter/vf_eq.c, which works in YUV):
 *     y  = dot(rgb, BT601)                 // luma
 *     y' = contrast * (y - 0.5) + 0.5 + brightness
 *     c' = y' + (rgb - y) * saturation     // chroma scaled about the luma axis
 * then the LUT, because `video_edit` appends `eq` BEFORE `lut3d`.
 *
 * The LUT texture is the 2D strip written by
 * `backend/scripts/make_lut_previews.py` (size tiles of size×size, blue across).
 * Its size is read back from the PNG height, so 16³/32³/33³ all work.
 *
 * Anything that can fail — no WebGL, a tainted canvas, a missing preview PNG —
 * falls back to the untouched <OffthreadVideo>. A preview is never worth
 * breaking the edit session over.
 */

import { useEffect, useRef, useState } from "react";
import { Html5Video, OffthreadVideo, useCurrentFrame } from "remotion";

import type { EqSpec } from "@/types/editor";

const VERT = `
attribute vec2 aPos;
varying vec2 vUv;
void main() {
  vUv = vec2((aPos.x + 1.0) * 0.5, 1.0 - (aPos.y + 1.0) * 0.5);
  gl_Position = vec4(aPos, 0.0, 1.0);
}`;

const FRAG = `
precision mediump float;
varying vec2 vUv;
uniform sampler2D uVideo;
uniform sampler2D uLut;
uniform float uLutSize;   // 0 = no LUT bound
uniform float uBright;
uniform float uContrast;
uniform float uSat;

vec3 applyEq(vec3 c) {
  float y = dot(c, vec3(0.299, 0.587, 0.114));
  float yo = uContrast * (y - 0.5) + 0.5 + uBright;
  return clamp(yo + (c - vec3(y)) * uSat, 0.0, 1.0);
}

vec3 applyLut(vec3 c) {
  float sz = uLutSize;
  float last = sz - 1.0;
  float b = clamp(c.b, 0.0, 1.0) * last;
  float b0 = floor(b);
  float b1 = min(b0 + 1.0, last);
  float f = b - b0;
  float x = clamp(c.r, 0.0, 1.0) * last + 0.5;
  float v = (clamp(c.g, 0.0, 1.0) * last + 0.5) / sz;
  vec3 s0 = texture2D(uLut, vec2((b0 * sz + x) / (sz * sz), v)).rgb;
  vec3 s1 = texture2D(uLut, vec2((b1 * sz + x) / (sz * sz), v)).rgb;
  return mix(s0, s1, f);
}

void main() {
  vec3 c = texture2D(uVideo, vUv).rgb;
  c = applyEq(c);
  if (uLutSize > 1.0) c = applyLut(c);
  gl_FragColor = vec4(c, 1.0);
}`;

export const IDENTITY_EQ: EqSpec = { brightness: 0, contrast: 1, saturation: 1 };

export function isIdentityEq(eq: EqSpec | undefined): boolean {
  if (!eq) return true;
  return eq.brightness === 0 && eq.contrast === 1 && eq.saturation === 1;
}

/** LUTS_DIR-relative .cube -> the flat preview PNG name the script writes. */
export function lutPreviewUrl(origin: string, lut: string): string {
  const flat = lut.replace(/\\/g, "/").replace(/\//g, "__").replace(/\.cube$/i, "");
  return `${origin}/static/assets/luts/_preview/${encodeURIComponent(flat)}.png`;
}

function compile(gl: WebGLRenderingContext, type: number, src: string): WebGLShader {
  const sh = gl.createShader(type)!;
  gl.shaderSource(sh, src);
  gl.compileShader(sh);
  if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
    throw new Error(gl.getShaderInfoLog(sh) ?? "shader compile failed");
  }
  return sh;
}

interface GlState {
  gl: WebGLRenderingContext;
  program: WebGLProgram;
  videoTex: WebGLTexture;
  lutTex: WebGLTexture;
  loc: Record<string, WebGLUniformLocation | null>;
}

export interface ColorVideoProps {
  src: string;
  muted: boolean;
  playbackRate: number;
  eq: EqSpec;
  /** Already-resolved preview PNG URL, or null for eq-only. */
  lutUrl: string | null;
  style?: React.CSSProperties;
}

export function ColorVideo({ src, muted, playbackRate, eq, lutUrl, style }: ColorVideoProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const glRef = useRef<GlState | null>(null);
  const lutSizeRef = useRef(0);
  const [failed, setFailed] = useState(false);
  // Bumped when the element becomes decodable. Without it a paused player that
  // mounts before the first frame decodes would draw nothing and stay black
  // until the user scrubbed.
  const [ready, setReady] = useState(0);
  const frame = useCurrentFrame();

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    const bump = () => setReady((n) => n + 1);
    video.addEventListener("loadeddata", bump);
    video.addEventListener("seeked", bump);
    return () => {
      video.removeEventListener("loadeddata", bump);
      video.removeEventListener("seeked", bump);
    };
  }, [src]);

  // ── one-time GL setup ───────────────────────────────────────────────────
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || failed) return;
    try {
      const gl = canvas.getContext("webgl", { premultipliedAlpha: false });
      if (!gl) throw new Error("no webgl context");

      const program = gl.createProgram()!;
      gl.attachShader(program, compile(gl, gl.VERTEX_SHADER, VERT));
      gl.attachShader(program, compile(gl, gl.FRAGMENT_SHADER, FRAG));
      gl.linkProgram(program);
      if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
        throw new Error(gl.getProgramInfoLog(program) ?? "link failed");
      }
      gl.useProgram(program);

      const buf = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, buf);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
      const aPos = gl.getAttribLocation(program, "aPos");
      gl.enableVertexAttribArray(aPos);
      gl.vertexAttribPointer(aPos, 2, gl.FLOAT, false, 0, 0);

      const mkTex = () => {
        const t = gl.createTexture()!;
        gl.bindTexture(gl.TEXTURE_2D, t);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
        return t;
      };
      const videoTex = mkTex();
      const lutTex = mkTex();

      glRef.current = {
        gl, program, videoTex, lutTex,
        loc: {
          uVideo: gl.getUniformLocation(program, "uVideo"),
          uLut: gl.getUniformLocation(program, "uLut"),
          uLutSize: gl.getUniformLocation(program, "uLutSize"),
          uBright: gl.getUniformLocation(program, "uBright"),
          uContrast: gl.getUniformLocation(program, "uContrast"),
          uSat: gl.getUniformLocation(program, "uSat"),
        },
      };
      gl.uniform1i(glRef.current.loc.uVideo!, 0);
      gl.uniform1i(glRef.current.loc.uLut!, 1);
    } catch (err) {
      console.warn("[editor] colour preview disabled:", err);
      setFailed(true);
    }
    return () => {
      const st = glRef.current;
      if (st) {
        st.gl.deleteTexture(st.videoTex);
        st.gl.deleteTexture(st.lutTex);
        st.gl.deleteProgram(st.program);
      }
      glRef.current = null;
    };
  }, [failed]);

  // ── LUT texture (re-uploaded only when the .cube changes) ───────────────
  useEffect(() => {
    lutSizeRef.current = 0;
    if (!lutUrl) return;
    let cancelled = false;
    const img = new Image();
    // The PNG lives on the API origin; without CORS the canvas would taint and
    // every subsequent readback/draw would throw.
    img.crossOrigin = "anonymous";
    img.onload = () => {
      const st = glRef.current;
      if (cancelled || !st) return;
      // Strip layout: width == size * size, height == size.
      if (img.height < 2 || img.width !== img.height * img.height) {
        console.warn("[editor] unexpected LUT strip shape", img.width, img.height);
        return;
      }
      const { gl } = st;
      gl.activeTexture(gl.TEXTURE1);
      gl.bindTexture(gl.TEXTURE_2D, st.lutTex);
      gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, 0);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB, gl.RGB, gl.UNSIGNED_BYTE, img);
      lutSizeRef.current = img.height;
      setReady((n) => n + 1);   // the texture arrived after the last draw
    };
    img.onerror = () => {
      // No preview PNG for this LUT yet — eq still previews, grade does not.
      console.info("[editor] no LUT preview texture:", lutUrl);
    };
    img.src = lutUrl;
    return () => { cancelled = true; };
  }, [lutUrl]);

  // ── per-frame draw ──────────────────────────────────────────────────────
  useEffect(() => {
    const st = glRef.current;
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!st || !video || !canvas || failed) return;
    if (video.readyState < 2) return;

    const w = video.videoWidth || canvas.width;
    const h = video.videoHeight || canvas.height;
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w;
      canvas.height = h;
    }

    const { gl, loc } = st;
    try {
      gl.viewport(0, 0, canvas.width, canvas.height);
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, st.videoTex);
      gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, 0);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB, gl.RGB, gl.UNSIGNED_BYTE, video);
      gl.activeTexture(gl.TEXTURE1);
      gl.bindTexture(gl.TEXTURE_2D, st.lutTex);
      gl.uniform1f(loc.uLutSize!, lutSizeRef.current);
      gl.uniform1f(loc.uBright!, eq.brightness);
      gl.uniform1f(loc.uContrast!, eq.contrast);
      gl.uniform1f(loc.uSat!, eq.saturation);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    } catch (err) {
      // SecurityError = the proxy response arrived without CORS headers.
      console.warn("[editor] colour preview draw failed:", err);
      setFailed(true);
    }
  }, [frame, ready, lutUrl, eq.brightness, eq.contrast, eq.saturation, failed]);

  if (failed) {
    return (
      <OffthreadVideo src={src} muted={muted} playbackRate={playbackRate}
                      style={style ?? { width: "100%", height: "100%", objectFit: "cover" }} />
    );
  }

  return (
    <>
      {/* The real element stays in the DOM (Remotion drives its currentTime and
          audio) but is never shown — the canvas is the visible surface. */}
      <Html5Video
        ref={videoRef}
        src={src}
        muted={muted}
        playbackRate={playbackRate}
        crossOrigin="anonymous"
        style={{ position: "absolute", width: 1, height: 1, opacity: 0, pointerEvents: "none" }}
      />
      <canvas
        ref={canvasRef}
        style={style ?? { width: "100%", height: "100%", objectFit: "cover" }}
      />
    </>
  );
}
