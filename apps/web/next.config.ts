import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  devIndicators: false,
  async headers() {
    return [{ source: "/sw.js", headers: [{ key: "Cache-Control", value: "no-cache, no-store, must-revalidate" }, { key: "Content-Type", value: "application/javascript; charset=utf-8" }] }];
  },
  // Keep the synthetic review route out of production route discovery. The
  // debug page/asset files use the `debug.tsx`/`debug.ts` extensions and are
  // only discoverable by the development server.
  pageExtensions: process.env.NODE_ENV === "production"
    ? ["tsx", "ts"]
    : ["tsx", "ts", "debug.tsx", "debug.ts"],
  // Allow the phone on the development LAN to load Next's HMR client.
  allowedDevOrigins: ["192.168.178.37", "192.168.2.152"],
  transpilePackages: ["@allies/cloud-client", "@allies/ally-motion"],
  turbopack: {
    root: path.resolve(__dirname, "../.."),
  },
};

export default nextConfig;
