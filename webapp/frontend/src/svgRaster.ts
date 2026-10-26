/** Crops a diagram's already-rendered SVG to a region and rasterizes it to
 * PNG, entirely client-side — the live SVG already in the DOM is the
 * source of truth, so this never asks the backend to re-render anything
 * (see webapp/backend/app/main.py's /api/export/pptx/generate, which only
 * ever receives finished PNG bytes). */

export interface BBox {
  x: number;
  y: number;
  w: number;
  h: number;
}

export function unionBBox(boxes: BBox[]): BBox {
  const x1 = Math.min(...boxes.map((b) => b.x));
  const y1 = Math.min(...boxes.map((b) => b.y));
  const x2 = Math.max(...boxes.map((b) => b.x + b.w));
  const y2 = Math.max(...boxes.map((b) => b.y + b.h));
  return { x: x1, y: y1, w: x2 - x1, h: y2 - y1 };
}

export function padBBox(box: BBox, padding: number): BBox {
  return { x: box.x - padding, y: box.y - padding, w: box.w + padding * 2, h: box.h + padding * 2 };
}

/** `svgMarkup` is a full `<svg ...>...</svg>` string (as served on
 * `DiagramResponse.svg`). Returns a base64 PNG with no `data:` prefix.
 * `scale` is raster pixels per SVG unit — the SVG itself has no DPI
 * concept (render_svg.py's root element is unitless px), so this purely
 * controls output sharpness. */
export async function rasterizeSvgRegion(svgMarkup: string, box: BBox, scale = 2): Promise<string> {
  const openTagEnd = svgMarkup.indexOf(">");
  const closeTagStart = svgMarkup.lastIndexOf("</svg>");
  if (openTagEnd < 0 || closeTagStart < 0) throw new Error("Not a valid SVG document");
  const inner = svgMarkup.slice(openTagEnd + 1, closeTagStart);

  const renderW = Math.max(1, Math.round(box.w * scale));
  const renderH = Math.max(1, Math.round(box.h * scale));
  const cropped =
    `<svg xmlns="http://www.w3.org/2000/svg" width="${renderW}" height="${renderH}" ` +
    `viewBox="${box.x} ${box.y} ${box.w} ${box.h}">${inner}</svg>`;

  const blobUrl = URL.createObjectURL(new Blob([cropped], { type: "image/svg+xml" }));
  try {
    const img = await new Promise<HTMLImageElement>((resolve, reject) => {
      const el = new Image();
      el.onload = () => resolve(el);
      el.onerror = () => reject(new Error("Could not rasterize this region of the diagram"));
      el.src = blobUrl;
    });
    const canvas = document.createElement("canvas");
    canvas.width = renderW;
    canvas.height = renderH;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("Canvas 2D context unavailable");
    // White backing, not transparent — PowerPoint slides default to a white
    // background and the diagram's own shapes assume one too (see
    // render_svg.py's node fills), so a transparent PNG would show through
    // to whatever's behind the placeholder shape instead.
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, renderW, renderH);
    ctx.drawImage(img, 0, 0, renderW, renderH);
    const dataUrl = canvas.toDataURL("image/png");
    return dataUrl.slice(dataUrl.indexOf(",") + 1);
  } finally {
    URL.revokeObjectURL(blobUrl);
  }
}
