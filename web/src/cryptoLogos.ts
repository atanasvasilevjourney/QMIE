/** Bundled under `web/public/crypto/*.png` — identification marks only. */

export const CRYPTO_LOGOS = [
  'btc',
  'eth',
  'sol',
  'bnb',
  'xrp',
  'doge',
  'ada',
  'avax',
  'link',
  'pol',
  'dot',
  'ltc',
  'trx',
  'atom',
  'near',
  'apt',
  'arb',
  'op',
  'sui',
  'inj',
  'fil',
  'render',
  'tia',
  'sei',
  'ordi',
  'wld',
  'pepe',
  'bonk',
  'uni',
  'ton',
  'shib',
  'ape',
  'wif',
] as const

export type CryptoLogoId = (typeof CRYPTO_LOGOS)[number]

const LOGO_SET = new Set<string>(CRYPTO_LOGOS)

const ALIAS: Record<string, CryptoLogoId> = {
  MATIC: 'pol',
  POLYGON: 'pol',
  POL: 'pol',
  RNDR: 'render',
  RENDER: 'render',
  WBTC: 'btc',
  WETH: 'eth',
  STETH: 'eth',
}

export const LOGO_HALO: Record<string, string> = {
  btc: '#f7931a',
  eth: '#8ca7ff',
  sol: '#14f195',
  bnb: '#f3ba2f',
  xrp: '#e5e7eb',
  doge: '#c2a633',
  ada: '#3468d1',
  avax: '#e84142',
  link: '#2a5ada',
  pol: '#7b3fe4',
  dot: '#e6007a',
  ltc: '#bfbbbb',
  trx: '#ff0013',
  atom: '#2e3148',
  near: '#d8d8d8',
  apt: '#08d3b4',
  arb: '#28a0f0',
  op: '#ff0420',
  sui: '#4da2ff',
  inj: '#00f2fe',
  fil: '#0090ff',
  render: '#ff4d00',
  tia: '#7b2cbf',
  sei: '#9b1d20',
  ordi: '#f7931a',
  wld: '#ffffff',
  pepe: '#3d9a3d',
  bonk: '#f5a623',
  uni: '#ff007a',
  ton: '#0098ea',
  shib: '#ffa409',
  ape: '#0054f9',
  wif: '#c45c26',
}

export function tickerToLogoId(symbol: string): CryptoLogoId | null {
  const raw = symbol.replace(/[-_/]/g, '').toUpperCase().replace(/USDT$/, '').replace(/^1000/, '')
  const aliased = ALIAS[raw]
  if (aliased) return aliased
  const id = raw.toLowerCase()
  return LOGO_SET.has(id) ? (id as CryptoLogoId) : null
}

export function orbitLogoIds(radarSymbols: string[], count: number): CryptoLogoId[] {
  const picked: CryptoLogoId[] = []
  const seen = new Set<string>()
  for (const symbol of radarSymbols) {
    const id = tickerToLogoId(symbol)
    if (!id || seen.has(id)) continue
    seen.add(id)
    picked.push(id)
    if (picked.length >= count) return picked
  }
  for (const id of CRYPTO_LOGOS) {
    if (seen.has(id)) continue
    seen.add(id)
    picked.push(id)
    if (picked.length >= count) return picked
  }
  while (picked.length < count && CRYPTO_LOGOS.length) {
    picked.push(CRYPTO_LOGOS[picked.length % CRYPTO_LOGOS.length])
  }
  return picked
}

const imageCache = new Map<string, Promise<HTMLImageElement>>()

export function loadCryptoLogo(id: string): Promise<HTMLImageElement> {
  let pending = imageCache.get(id)
  if (!pending) {
    pending = new Promise((resolve, reject) => {
      const img = new Image()
      img.decoding = 'async'
      img.onload = () => resolve(img)
      img.onerror = () => reject(new Error(`logo ${id}`))
      img.src = `/crypto/${id}.png`
    })
    imageCache.set(id, pending)
  }
  return pending
}
