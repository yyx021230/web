import assert from 'node:assert/strict';

process.env.BACKEND_ORIGIN = 'http://legacy:8000';
process.env.HERMES_BACKEND_ORIGIN = 'http://hermes:8000';
const { default: config } = await import('../frontend/next.config.mjs?split');
assert.deepEqual(await config.rewrites(), [
  { source: '/api/backend/hermes-workflows/:path*', destination: 'http://hermes:8000/api/v1/hermes-workflows/:path*' },
  { source: '/api/backend/admin/hermes-workflows/:path*', destination: 'http://hermes:8000/api/v1/admin/hermes-workflows/:path*' },
  { source: '/api/backend/:path*', destination: 'http://legacy:8000/api/v1/:path*' },
  { source: '/uploads/:path*', destination: 'http://legacy:8000/uploads/:path*' },
]);
delete process.env.HERMES_BACKEND_ORIGIN;
const { default: fallback } = await import('../frontend/next.config.mjs?fallback');
assert((await fallback.rewrites()).every(row => row.destination.startsWith('http://legacy:8000/')));
console.log('Hermes-only routing and monolithic fallback passed');
