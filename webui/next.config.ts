import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  serverExternalPackages: ["@h1/sdk", "serialport"],
  async redirects() {
    return [
      {
        source: "/",
        destination: "/acquisition",
        permanent: false,
      },
    ];
  },
};

export default nextConfig;
