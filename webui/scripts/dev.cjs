/* Production-style static server for dist/ with API reverse-proxy.
 * Pure Node http — no spawns. Serves the built SPA at :5173 and
 * proxies /api/* to the FastAPI backend at :8010. */
const http = require('http')
const fs = require('fs')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')
const DIST = path.join(ROOT, 'dist')
const PORT = Number(process.env.WEBUI_PORT || 5173)
const API = process.env.API_URL || 'http://127.0.0.1:8010'

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.json': 'application/json',
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`)

  if (url.pathname.startsWith('/api/')) {
    // reverse proxy to FastAPI
    const opts = {
      host: new URL(API).hostname,
      port: new URL(API).port,
      path: url.pathname + url.search,
      method: req.method,
      headers: { ...req.headers, host: new URL(API).host },
    }
    const up = http.request(opts, ur => {
      res.writeHead(ur.statusCode, ur.headers)
      ur.pipe(res)
    })
    up.on('error', e => {
      res.writeHead(502, { 'content-type': 'application/json' })
      res.end(JSON.stringify({ error: `backend unreachable: ${e.message}` }))
    })
    req.pipe(up)
    return
  }

  // static
  let file = path.join(DIST, url.pathname === '/' ? 'index.html' : url.pathname)
  if (!file.startsWith(DIST)) { res.writeHead(403); res.end(); return }
  if (!fs.existsSync(file) || fs.statSync(file).isDirectory()) file = path.join(DIST, 'index.html')
  const ext = path.extname(file)
  res.writeHead(200, {
    'content-type': MIME[ext] || 'application/octet-stream',
    'cache-control': ext === '.html' ? 'no-cache' : 'public, max-age=300',
  })
  fs.createReadStream(file).pipe(res)
})

server.listen(PORT, () => {
  console.log(`Revenue Guard UI  →  http://127.0.0.1:${PORT}`)
  console.log(`proxying /api/*   →  ${API}`)
})
