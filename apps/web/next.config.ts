import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Allow the phone on the development LAN to load Next's HMR client.
  allowedDevOrigins: ["192.168.178.37"],
  transpilePackages: ["@allies/cloud-client"],
  turbopack: {
    root: path.resolve(__dirname, "../.."),
  },
};

export default nextConfig;
