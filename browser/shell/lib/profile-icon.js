/* The toolbar's profile button (Calmaria, 2026-11): monochrome, in the toolbar's icon colour, the
   profile's solid glyph (or initial) on a square of that colour at 14 %. The profile's own colour shows
   once per window, in the band the browser draws; the toolbar does not repeat it. A temporary profile
   shows the hourglass (no dashes at 16 px, where they read as a letter). Glyphs come from
   modules/NulavioAvatars.sys.mjs, so every surface draws the same shapes. */

import { AVATAR_GLYPHS, SPECIAL_GLYPHS, profileInitial } from "../modules/NulavioAvatars.sys.mjs";

// color.{light,dark}.chrome.icon; the private chrome is dark in both themes (docs/brand/tokens.json).
export const TOOLBAR_INK = Object.freeze({ light: "#23495A", dark: "#BFD0D6", private: "#BFD0D6" });

export function drawProfileIcon(profile, { ink = TOOLBAR_INK.light, sizes = [16, 32] } = {}) {
  const d = profile.temporary ? SPECIAL_GLYPHS.temporary : AVATAR_GLYPHS[profile.avatar] ?? null;
  const letter = d ? null : profileInitial(profile.name);
  const imageData = {};
  for (const size of sizes) {
    const canvas = new OffscreenCanvas(size, size);
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = ink;
    ctx.globalAlpha = 0.14;
    ctx.beginPath();
    ctx.roundRect(0, 0, size, size, size * 0.3);
    ctx.fill();
    ctx.globalAlpha = 1;
    if (letter) {
      ctx.font = `600 ${Math.round(size * 0.625)}px system-ui, sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(letter, size / 2, size / 2 + size * 0.02);
    } else {
      // The 24-unit glyph fills the square as in the band (about 11 px of 16).
      ctx.scale(size / 24, size / 24);
      ctx.fill(new Path2D(d ?? SPECIAL_GLYPHS.person), "evenodd");
    }
    imageData[size] = ctx.getImageData(0, 0, size, size);
  }
  return imageData;
}
