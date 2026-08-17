/** @type {import('next').NextConfig} */
const backendOrigin = process.env.BACKEND_ORIGIN || 'http://localhost:8000';

const defaultImageOrigins = [
  'https://cdn.dancf.com',
  'https://gd-filems.dancf.com',
  'https://gdesign-dam.dancf.com',
  'https://gdesign-dam-hw.dancf.com',
  'https://st-gdx.dancf.com',
  'https://st0.dancf.com',
  'https://ci.xiaohongshu.com',
  'http://ci.xiaohongshu.com',
  'https://test260415.oss-cn-hangzhou.aliyuncs.com',
  'https://img.wuzuapi.com',
  'http://localhost:8000',
  'http://127.0.0.1:8000',
];

const configuredImageOrigins = (process.env.NEXT_PUBLIC_IMAGE_ALLOWED_ORIGINS || '')
  .split(',')
  .map((origin) => origin.trim())
  .filter(Boolean);
const imageSources = Array.from(new Set([
  ...defaultImageOrigins,
  ...configuredImageOrigins,
  // AI image providers and vehicle libraries may return new OSS/CDN hosts.
  // Keep CSP strict for scripts/connect, but allow image rendering broadly.
  'https:',
  'http:',
]));

const isProd = process.env.NODE_ENV === 'production';
const scriptSrc = isProd
  // Next currently emits inline bootstrap/data scripts. A nonce-based CSP should
  // replace this fallback in the next auth/session hardening pass.
  ? "script-src 'self' 'unsafe-inline'"
  : "script-src 'self' 'unsafe-inline' 'unsafe-eval'";
const connectSrc = isProd
  ? "connect-src 'self' http://localhost:8000 http://127.0.0.1:8000"
  : "connect-src 'self' http://localhost:8000 http://127.0.0.1:8000 ws://localhost:* ws://127.0.0.1:*";

const csp = [
  "default-src 'self'",
  scriptSrc,
  "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
  "font-src 'self' https://fonts.gstatic.com data:",
  `img-src 'self' data: blob: ${imageSources.join(' ')}`,
  connectSrc,
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "object-src 'none'",
].join('; ');

const nextConfig = {
  output: 'standalone',
  images: {
    remotePatterns: [],
  },
  async headers() {
    return [
      {
        source: '/:path*',
        headers: [
          { key: 'Content-Security-Policy', value: csp },
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
          { key: 'X-Frame-Options', value: 'DENY' },
          { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=()' },
        ],
      },
    ];
  },
  async rewrites() {
    return [
      {
        source: '/api/backend/:path*',
        destination: `${backendOrigin}/api/v1/:path*`,
      },
      {
        source: '/uploads/:path*',
        destination: `${backendOrigin}/uploads/:path*`,
      },
    ];
  },
};

export default nextConfig;
