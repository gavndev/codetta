// Light/dark theme and the spot colour each album borrows from its cover.
// Part of Codetta's page; app.js is the entry point (see the note at its top).

import { $, icon, reducedMotion } from "./dom.js";
import { state } from "./state.js";
import { artUrlFor } from "./editor.js";

// ---- Theme -----------------------------------------------------------------------------------

export const THEMES = ["system", "light", "dark"];
export const THEME_LABEL = { system: "Theme: match system", light: "Theme: light", dark: "Theme: dark" };
export const THEME_ICON = { system: "auto", light: "sun", dark: "moon" };

export function getTheme() {
  try { return localStorage.getItem("codetta-theme") || "system"; } catch { return "system"; }
}

export function setTheme(theme) {
  try { localStorage.setItem("codetta-theme", theme); } catch { /* private mode */ }
  // Crossfade the whole page between themes where the browser supports it.
  if (document.startViewTransition && !reducedMotion()) document.startViewTransition(() => applyTheme(theme));
  else applyTheme(theme);
}

export function applyTheme(theme) {
  const root = document.documentElement;
  if (theme === "system") delete root.dataset.theme;
  else root.dataset.theme = theme;
  const btn = $("#theme-btn");
  btn.replaceChildren(icon(THEME_ICON[theme]));
  btn.title = THEME_LABEL[theme];
  btn.setAttribute("aria-label", THEME_LABEL[theme]);
  // Browser chrome / iOS status bar colour.
  for (const meta of document.querySelectorAll('meta[name="theme-color"]')) {
    const dark = meta.media.includes("dark");
    const color = theme === "system" ? (dark ? "#131418" : "#f7f8f8") : theme === "dark" ? "#131418" : "#f7f8f8";
    meta.content = color;
  }
  requestAnimationFrame(refitSpot); // the spot colour is fitted to the background's contrast
}

// ---- Spot colour: each album borrows one colour from its cover -------------------------------

const spotCache = new Map(); // cover hash -> [r, g, b] or null (a grey or unreadable cover)
let spotRgb = null; // the current cover's raw colour

const luminance = ([r, g, b]) => {
  const c = [r, g, b].map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; });
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
};
const contrast = (a, b) => { const [x, y] = [luminance(a), luminance(b)].sort((m, n) => n - m); return (x + 0.05) / (y + 0.05); };

function rgbToHsl([r, g, b]) {
  r /= 255; g /= 255; b /= 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b), l = (max + min) / 2;
  if (max === min) return [0, 0, l];
  const d = max - min, s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  const h = max === r ? (g - b) / d + (g < b ? 6 : 0) : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return [h / 6, s, l];
}
function hslToRgb([h, s, l]) {
  if (!s) return [l, l, l].map((v) => Math.round(v * 255));
  const q = l < 0.5 ? l * (1 + s) : l + s - l * s, p = 2 * l - q;
  const f = (t) => { t = (t + 1) % 1; return t < 1 / 6 ? p + (q - p) * 6 * t : t < 1 / 2 ? q : t < 2 / 3 ? p + (q - p) * (2 / 3 - t) * 6 : p; };
  return [f(h + 1 / 3), f(h), f(h - 1 / 3)].map((v) => Math.round(v * 255));
}

/** The cover's most characteristic colour: the strongest saturated hue, or null for grey covers. */
function coverColour(url) {
  return new Promise((resolve) => {
    const img = new Image();
    img.decoding = "async";
    img.onload = () => {
      try {
        const n = 32, c = document.createElement("canvas");
        c.width = c.height = n;
        const ctx = c.getContext("2d", { willReadFrequently: true });
        ctx.drawImage(img, 0, 0, n, n);
        const px = ctx.getImageData(0, 0, n, n).data;
        const bins = Array.from({ length: 24 }, () => ({ w: 0, r: 0, g: 0, b: 0 }));
        for (let i = 0; i < px.length; i += 4) {
          const rgb = [px[i], px[i + 1], px[i + 2]];
          const [h, s, l] = rgbToHsl(rgb);
          if (l < 0.12 || l > 0.92 || s < 0.2) continue;
          const bin = bins[Math.floor(h * 24) % 24], w = s * s;
          bin.w += w; bin.r += rgb[0] * w; bin.g += rgb[1] * w; bin.b += rgb[2] * w;
        }
        const best = bins.reduce((a, b) => (b.w > a.w ? b : a));
        resolve(best.w < 6 ? null : [best.r, best.g, best.b].map((v) => Math.round(v / best.w)));
      } catch { resolve(null); }
    };
    img.onerror = () => resolve(null);
    img.src = url;
  });
}

/** Fit a colour to the current background: saturated enough to read as colour,
 *  dark (or light) enough for 4.5:1 text contrast. */
function fitSpot(rgb) {
  const bg = (getComputedStyle(document.body).backgroundColor.match(/\d+/g) || [247, 248, 248]).slice(0, 3).map(Number);
  const dark = luminance(bg) < 0.2;
  let [h, s, l] = rgbToHsl(rgb);
  s = Math.min(0.85, Math.max(0.5, s));
  l = dark ? Math.max(l, 0.55) : Math.min(l, 0.45);
  for (let i = 0; i < 40 && contrast(hslToRgb([h, s, l]), bg) < 4.6; i++) l += dark ? 0.02 : -0.02;
  const [r, g, b] = hslToRgb([h, s, Math.min(0.95, Math.max(0.05, l))]);
  return `rgb(${r} ${g} ${b})`;
}

function refitSpot() {
  const root = document.documentElement;
  if (spotRgb) root.style.setProperty("--spot", fitSpot(spotRgb));
  else root.style.removeProperty("--spot"); // back to the house colour
}

/** Take the spot colour from the open folder's cover (or go back to the house colour). */
export async function updateSpot() {
  const f = state.folder;
  const cover = !f?.search && f?.tracks.find((t) => t.art);
  if (!cover) { spotRgb = null; refitSpot(); return; }
  const key = cover.art.hash;
  if (!spotCache.has(key)) {
    const rgb = await coverColour(artUrlFor(cover));
    if (spotCache.size > 300) spotCache.clear();
    spotCache.set(key, rgb);
  }
  if (state.folder !== f) return; // moved on while the cover loaded
  spotRgb = spotCache.get(key);
  refitSpot();
}
