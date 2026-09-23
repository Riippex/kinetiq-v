import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  transpilePackages: ["@kinetiq/session-client"],
};

export default nextConfig;
