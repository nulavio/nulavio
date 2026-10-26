/* Toolbar icon for the current profile: its identity colour with its initial,
   drawn locally. Colours are generated from the design tokens
   (lib/identity-colors.js), so there is one source of truth. */

import { IDENTITY_COLORS } from "./identity-colors.js";

export function drawProfileIcon(profile, sizes = [16, 32]) {
  const fill = IDENTITY_COLORS[profile.color] ?? IDENTITY_COLORS.slate;
  const ink = IDENTITY_COLORS.on;
  const letter = ([...String(profile.name ?? "").trim()][0] ?? "?").toLocaleUpperCase();
  const imageData = {};
  for (const size of sizes) {
    const canvas = new OffscreenCanvas(size, size);
    const ctx = canvas.getContext("2d");
    const r = size / 2;
    ctx.beginPath();
    ctx.arc(r, r, r - size / 16, 0, Math.PI * 2);
    ctx.fillStyle = fill;
    ctx.fill();
    ctx.lineWidth = size / 16;
    ctx.strokeStyle = ink;
    ctx.stroke();
    ctx.fillStyle = ink;
    ctx.font = `600 ${Math.round(size * 0.6)}px system-ui, sans-serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(letter, r, r + size * 0.04);
    imageData[size] = ctx.getImageData(0, 0, size, size);
  }
  return imageData;
}
