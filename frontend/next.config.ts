import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
  experimental: {
    turbo: {
      resolveAlias: {
        underscore: 'lodash',
        mocha: { browser: 'mocha/browser-entry.js' },
      },
    },
  },
  webpack: (config) => {
    config.resolve.alias["@"] = path.join(__dirname, ".");
    return config;
  },
};

export default nextConfig;
