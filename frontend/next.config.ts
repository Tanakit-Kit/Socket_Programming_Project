import type { NextConfig } from "next";

const host = process.env.HOST_IP || "localhost";

const nextConfig: NextConfig = {
  /* config options here */
  experimental: {
    agentFeedback: true,
  },
  cacheComponents: true,
  partialPrefetching: true,

  allowedDevOrigins: (process.env.DEV_ALLOWED_ORIGINS || host)
    .split(',')
    .map((hostname) => hostname.trim())
    .filter(Boolean),

  env: {
    NEXT_PUBLIC_CHAT_WS_URL:
      process.env.NEXT_PUBLIC_CHAT_WS_URL || `ws://${host}:5000`,
  },
};

export default nextConfig;
