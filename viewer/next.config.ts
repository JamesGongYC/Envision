import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  async redirects() {
    return [
      { source: '/about', destination: '/how-it-works', permanent: true },
    ];
  },
};

export default nextConfig;
