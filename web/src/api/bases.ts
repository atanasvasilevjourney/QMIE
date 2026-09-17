/** Ordered fetch prefixes for the QMIE FastAPI. First match that returns JSON 2xx wins. */

export const RENDER_API = 'https://qmie.onrender.com'

export function isScannerHost(hostname: string): boolean {
  return hostname === 'qmie.onrender.com' || hostname.endsWith('.onrender.com')
}

export function isLocalHost(hostname: string): boolean {
  return !hostname || hostname === 'localhost' || hostname === '127.0.0.1'
}

export function isVercelHost(hostname: string): boolean {
  return hostname === 'qmie.vercel.app' || hostname.endsWith('.vercel.app')
}

/** Static HTML hosts must not call same-origin /health — that is the SPA, not FastAPI. */
export function hostnameApiFallback(hostname: string): string {
  if (isLocalHost(hostname) || isScannerHost(hostname)) return ''
  return RENDER_API
}

function originHost(origin: string): string {
  try {
    return new URL(origin).hostname
  } catch {
    return ''
  }
}

export function resolveApiBases(
  envApi?: string | null,
  hostname?: string,
): string[] {
  const extra = (envApi || '').trim().replace(/\/$/, '')
  const host =
    hostname ??
    (typeof window !== 'undefined' ? window.location.hostname : '')

  if (isLocalHost(host)) {
    const local = [
      '/qmie',
      'http://127.0.0.1:8080',
      'http://localhost:8080',
      '',
    ]
    if (extra && !isVercelHost(originHost(extra))) {
      return [extra, ...local]
    }
    return local
  }

  if (isScannerHost(host)) {
    return extra && extra !== RENDER_API ? [extra, ''] : ['']
  }

  // Vercel, custom domains, GitHub pages: never same-origin.
  const envOk = extra && !isVercelHost(originHost(extra)) ? extra : ''
  const implied = envOk || hostnameApiFallback(host) || RENDER_API
  return [...new Set([implied, RENDER_API].filter(Boolean))]
}
