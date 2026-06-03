const nextConfig = {
  output: 'standalone',
  distDir: '.next',
  images: { unoptimized: true },
  // Disable aggressive caching and static optimization for active development
  experimental: {
    // Next.js 15+
    staleTimes: {
      dynamic: 0,
      static: 0,
    },
  },
  // Force all pages to be dynamically rendered (no static caching)
  async headers() {
    return [
      {
        source: '/:path*',
        headers: [
          { key: 'Cache-Control', value: 'no-store, no-cache, must-revalidate, proxy-revalidate' },
          { key: 'Pragma', value: 'no-cache' },
          { key: 'Expires', value: '0' },
        ],
      },
    ];
  },
};

module.exports = nextConfig;
