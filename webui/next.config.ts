import type { NextConfig } from "next";

const nextConfig: NextConfig = {
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
