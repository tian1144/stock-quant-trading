const getBaseUrl = () => {
  // #ifdef H5
  return ''
  // #endif
  // #ifndef H5
  return 'http://localhost:8000'
  // #endif
}

const BASE_URL = getBaseUrl()

export const request = (url, method = 'GET', data = {}) => {
  return new Promise((resolve, reject) => {
    uni.request({
      url: BASE_URL + url, method, data,
      header: { 'Content-Type': 'application/json' },
      success: (res) => { res.statusCode === 200 ? resolve(res.data) : reject(res) },
      fail: (err) => reject(err)
    })
  })
}

export const getStockList = (params = {}) => {
  const { limit = 50, offset = 0 } = params
  return request(`/api/v1/stocks?limit=${limit}&offset=${offset}`)
}

export const searchStocks = (params = {}) => {
  const { keyword = '', limit = 20 } = params
  return request(`/api/v1/stocks/search?keyword=${encodeURIComponent(keyword)}&limit=${limit}`)
}

export const getStockQuote = (code) => request(`/api/v1/market/snapshot/${code}`)

export const getStockQuotes = (codes = []) => request(`/api/v1/market/snapshots?codes=${codes.join(',')}`)

export const syncStockList = () => request('/api/v1/stocks/sync', 'POST')
