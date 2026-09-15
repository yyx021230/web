const INTERNAL_UPLOAD_PREFIX = '/uploads/';

export function getImagePreviewUrl(source: string, width = 640, quality = 70): string {
  if (!source.startsWith(INTERNAL_UPLOAD_PREFIX)) return source;
  return `/_next/image?url=${encodeURIComponent(source)}&w=${width}&q=${quality}`;
}
