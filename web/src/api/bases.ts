/** Ordered fetch prefixes for the QMIE FastAPI. First match that returns 2xx wins. */
export function resolveApiBases(envApi?: string | null): string[] {
  const extra = (envApi || '').trim().replace(/\/$/, '')
  const local = [
    '/qmie',
    'http://127.0.0.1:8080',
    'http://localhost:8080',
    '',
  ]
  return extra ? [extra, ...local] : local
}
