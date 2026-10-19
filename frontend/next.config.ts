import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Self-contained server in .next/standalone for the production image (frontend/Dockerfile).
  output: "standalone",
};

export default nextConfig;
