/* A QR code as SVG from rows of modules ("1" dark, "0" light), which the engine's own encoder
   computes in the parent process (NulavioVault.phoneStart). Always dark on light, with the
   quiet zone the standard asks for, so phone cameras read it in either theme. */

const SVG = "http://www.w3.org/2000/svg";

export function qrSvg(rows, label, code = "") {
  const n = rows.length;
  const svg = document.createElementNS(SVG, "svg");
  svg.dataset.code = code; // what the image shows, nothing more
  svg.setAttribute("viewBox", `0 0 ${n + 8} ${n + 8}`);
  svg.setAttribute("class", "qr");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", label);
  svg.setAttribute("shape-rendering", "crispEdges");
  const background = document.createElementNS(SVG, "rect");
  background.setAttribute("width", String(n + 8));
  background.setAttribute("height", String(n + 8));
  background.setAttribute("fill", "#ffffff");
  svg.append(background);
  let d = "";
  rows.forEach((row, y) => {
    for (let x = 0; x < row.length; x++) {
      if (row[x] === "1") {
        d += `M${x + 4} ${y + 4}h1v1h-1z`;
      }
    }
  });
  const modules = document.createElementNS(SVG, "path");
  modules.setAttribute("d", d);
  modules.setAttribute("fill", "#000000");
  svg.append(modules);
  return svg;
}
