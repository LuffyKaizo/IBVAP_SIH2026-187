// MJPEG stream URL builder with loopback host rotation.
//
// Chromium limits each host to 6 concurrent HTTP/1.1 connections, so a page
// that opens one MJPEG <img> per camera can only ever load 6 streams - every
// 7th request is queued indefinitely and the tile stays blank forever. This
// was observed with 7 cameras registered: the dashboard loaded 6 tiles and
// the 7th /video/stream request never received a response.
//
// Rotating stream URLs across the two loopback host aliases (localhost and
// 127.0.0.1) gives each host its own 6-connection pool (12 streams total).
// The rotation is deterministic per camera id, so every view of the same
// camera uses an identical URL and in-flight requests still coalesce.
//
// Non-loopback deployments (VITE_AI_SERVICE_URL pointing at a real host) are
// left untouched - aliases only work for loopback addresses.
export function streamBaseUrl(aiBase: string, cameraId: string): string {
  const m = aiBase.match(/^(https?:\/\/)([^/:]+)(:\d+)?(.*)$/);
  if (!m) return aiBase;
  const [, scheme, host, port = '', rest] = m;
  const isLoopback = host === 'localhost' || /^127\./.test(host);
  if (!isLoopback) return aiBase;
  let sum = 0;
  for (let i = 0; i < cameraId.length; i++) sum += cameraId.charCodeAt(i);
  const target = sum % 2 === 0 ? 'localhost' : '127.0.0.1';
  if (target === host) return aiBase;
  return `${scheme}${target}${port}${rest}`;
}
