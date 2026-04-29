const API_BASE = '/api'

export const api = {
  async getMarketOverview() {
    const resp = await fetch(`${API_BASE}/market/overview`)
    const data = await resp.json()
    return data.success ? data.data : null
  },

  async getMarketStatus() {
    const resp = await fetch(`${API_BASE}/market/status`)
    const data = await resp.json()
    return data.success ? data.data : null
  },

  async getRealtime(symbol: string) {
    const resp = await fetch(`${API_BASE}/stock/realtime/${symbol}`)
    const data = await resp.json()
    return data.success ? data.data : null
  },

  async getHistory(symbol: string, period = '1y', klineType = 'daily', adjust = '') {
    const url = new URL(`${API_BASE}/stock/history/${symbol}`)
    url.searchParams.set('period', period)
    url.searchParams.set('kline_type', klineType)
    if (adjust) url.searchParams.set('adjust', adjust)
    const resp = await fetch(url.toString())
    const data = await resp.json()
    return data.success ? data.data : null
  },

  async getFundamentals(symbol: string) {
    const resp = await fetch(`${API_BASE}/stock/fundamentals/${symbol}`)
    const data = await resp.json()
    return data.success ? data.data : null
  },

  async getIndicators(symbol: string, period = '1y', klineType = 'daily') {
    const url = new URL(`${API_BASE}/stock/indicators/${symbol}`)
    url.searchParams.set('period', period)
    url.searchParams.set('kline_type', klineType)
    const resp = await fetch(url.toString())
    const data = await resp.json()
    return data.success ? data.data : null
  },

  async getWatchlist() {
    const resp = await fetch(`${API_BASE}/watchlist`)
    const data = await resp.json()
    return data.success ? data.data : null
  },

  async addToWatchlist(symbol: string) {
    const url = new URL(`${API_BASE}/watchlist/add`)
    url.searchParams.set('symbol', symbol)
    const resp = await fetch(url.toString(), { method: 'POST' })
    const data = await resp.json()
    return data.success ? data.data : null
  },

  async removeFromWatchlist(symbol: string) {
    const url = new URL(`${API_BASE}/watchlist/remove`)
    url.searchParams.set('symbol', symbol)
    const resp = await fetch(url.toString(), { method: 'POST' })
    const data = await resp.json()
    return data.success ? data.data : null
  },

  async search(query: string, limit = 10) {
    const url = new URL(`${API_BASE}/search`)
    url.searchParams.set('q', query)
    url.searchParams.set('limit', String(limit))
    const resp = await fetch(url.toString())
    const data = await resp.json()
    return data.success ? data.data : null
  },

  async getAccount() {
    const resp = await fetch(`${API_BASE}/trading/account`)
    const data = await resp.json()
    return data.success ? data.data : null
  },

  async getTradeHistory(limit = 100) {
    const url = new URL(`${API_BASE}/trading/history`)
    url.searchParams.set('limit', String(limit))
    const resp = await fetch(url.toString())
    const data = await resp.json()
    return data.success ? data.data : null
  },

  async buy(symbol: string, price: number, shares: number, options: {
    name?: string
    market?: string
    stopLoss?: number
    takeProfit?: number
    strategy?: string
  } = {}) {
    const url = new URL(`${API_BASE}/trading/buy`)
    url.searchParams.set('symbol', symbol)
    url.searchParams.set('price', String(price))
    url.searchParams.set('shares', String(shares))
    if (options.name) url.searchParams.set('name', options.name)
    if (options.market) url.searchParams.set('market', options.market)
    if (options.stopLoss) url.searchParams.set('stop_loss', String(options.stopLoss))
    if (options.takeProfit) url.searchParams.set('take_profit', String(options.takeProfit))
    if (options.strategy) url.searchParams.set('strategy', options.strategy)
    const resp = await fetch(url.toString(), { method: 'POST' })
    const data = await resp.json()
    return data.success ? data.data : null
  },

  async sell(symbol: string, price: number, shares?: number, reason = 'manual') {
    const url = new URL(`${API_BASE}/trading/sell`)
    url.searchParams.set('symbol', symbol)
    url.searchParams.set('price', String(price))
    if (shares) url.searchParams.set('shares', String(shares))
    url.searchParams.set('reason', reason)
    const resp = await fetch(url.toString(), { method: 'POST' })
    const data = await resp.json()
    return data.success ? data.data : null
  },
}