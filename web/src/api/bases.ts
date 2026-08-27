/** Ordered fetch prefixes for the QMIE FastAPI. First match that returns 2xx wins. */

export const RENDER_API = 'https://qmie.onrender.com'

export function hostnameApiFallback(hostname: string): string {
  if (hostname === 'qmie.vercel.app' || hostname.endsWith('.vercel.app')) {
    return RENDER_API
  }
  return ''
}

export function resolveApiBases(
  envApi?: string | null,
  hostname?: string,
): string[] {
  const extra = (envApi || '').trim().replace(/\/$/, '')
  const host =
    hostname ??
    (typeof window !== 'undefined' ? window.location.hostname : '')
  const isLocal = !host || host === 'localhost' || host === '127.0.0.1'
  if (isLocal) {
    const local = [
      '/qmie',
      'http://127.0.0.1:8080',
      'http://localhost:8080',
      '',
    ]
    return extra ? [extra, ...local] : local
  }
  const implied = extra || hostnameApiFallback(host)
  return implied ? [implied] : ['']
}
