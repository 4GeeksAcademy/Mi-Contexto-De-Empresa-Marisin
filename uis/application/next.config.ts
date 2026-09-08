import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { NextConfig } from "next";

const currentDir = dirname(fileURLToPath(import.meta.url));

const backendOrigin = (process.env.BACKEND_INTERNAL_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");

const nextConfig: NextConfig = {
  reactStrictMode: true,
  turbopack: {
    root: join(currentDir, "../.."),
  },
  async rewrites() {
    return [{ source: "/backend/:path*", destination: `${backendOrigin}/:path*` }];
  },
};

export default nextConfig;
