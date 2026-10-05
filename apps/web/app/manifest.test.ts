import path from "node:path";
import { fileURLToPath } from "node:url";

import sharp from "sharp";
import { describe, expect, it } from "vitest";

import manifest from "./manifest";

const pwaAssetDirectory = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "public", "pwa");

describe("web app manifest", () => {
  it("launches the app route inside the whole Allies scope", () => {
    expect(manifest()).toMatchObject({
      name: "allies",
      short_name: "allies",
      start_url: "/app",
      scope: "/",
      display: "standalone",
      background_color: "#ffffff",
      theme_color: "#ff5800",
    });
  });

  it("declares raster icons for regular, maskable, and Apple launches", () => {
    const icons = manifest().icons ?? [];
    expect(icons).toEqual(expect.arrayContaining([
      { src: "/pwa/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/pwa/icon-512.png", sizes: "512x512", type: "image/png" },
      { src: "/pwa/icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
      { src: "/pwa/apple-touch-icon.png", sizes: "180x180", type: "image/png" },
    ]));
  });

  it("ships every declared icon at its declared dimensions with an opaque Apple icon", async () => {
    const icons = manifest().icons ?? [];
    for (const icon of icons) {
      const metadata = await sharp(path.join(pwaAssetDirectory, icon.src.replace(/^\/pwa\//u, ""))).metadata();
      if (!icon.sizes) throw new Error(`Missing declared size for ${icon.src}`);
      const [width, height] = icon.sizes.split("x").map(Number);
      expect(metadata.width).toBe(width);
      expect(metadata.height).toBe(height);
      expect(metadata.format).toBe("png");
    }

    const apple = await sharp(path.join(pwaAssetDirectory, "apple-touch-icon.png"))
      .ensureAlpha()
      .raw()
      .toBuffer({ resolveWithObject: true });
    const corners = [
      [0, 0],
      [apple.info.width - 1, 0],
      [0, apple.info.height - 1],
      [apple.info.width - 1, apple.info.height - 1],
    ];
    expect(corners.map(([x, y]) => apple.data[(y * apple.info.width + x) * apple.info.channels + 3])).toEqual([255, 255, 255, 255]);
  });
});
