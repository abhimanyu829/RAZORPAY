/* Browser-boot test using jsdom — a real DOM implementation.
 * Loads dist/index.html in jsdom, executes app.js as the browser would,
 * and asserts the control center renders (nav title, KPI labels). */
const fs = require('fs')
const path = require('path')
const { JSDOM } = require('jsdom')

const DIST = path.resolve(__dirname, '../dist')
const html = fs.readFileSync(path.join(DIST, 'index.html'), 'utf-8')
const js = fs.readFileSync(path.join(DIST, 'assets/app.js'), 'utf-8')

const dom = new JSDOM(html, {
  url: 'http://127.0.0.1:5173/',
  runScripts: 'outside-only',
  pretendToBeVisual: true,
})
const { window } = dom

// optional second pass: deep-link to a case via ?case=CASE-9001
if (process.argv.includes('--case')) {
  const cid = process.argv[process.argv.indexOf('--case') + 1]
  window.history.replaceState({}, '', '/?case=' + cid)
  dom.window.location.hash = ''
}

// fetch → proxy through to the real live API (that's what the browser does)
window.fetch = (input, init) => {
  const url = typeof input === 'string' ? input : input.url
  const target = 'http://127.0.0.1:8010' + new URL(url, 'http://127.0.0.1:5173').pathname
    + new URL(url, 'http://127.0.0.1:5173').search
  return fetch(target, init).then(async r => ({
    ok: r.ok, status: r.status,
    json: async () => { const t = await r.text(); return t ? JSON.parse(t) : {} },
    text: () => r.text(),
  }))
}

// stub localStorage default key (jsdom has localStorage, but ensure value)
window.localStorage.setItem('rg_api_key', 'rg-admin-key')

let bootError = null
window.addEventListener('error', e => { bootError = e.error || e.message })

try {
  window.eval(js)
} catch (e) {
  console.log('EVAL FAIL:', e.message)
  process.exit(1)
}

// wait for React render + fetch round-trips
setTimeout(() => {
  const text = window.document.body.textContent || ''
  const checks = [
    ['nav title', text.includes('REVENUE GUARD')],
    ['KPI label', text.includes('Revenue Analysed')],
    ['leakage KPI', text.includes('Leakage Detected')],
    ['recovery rate', text.includes('Recovery Rate')],
    ['money rendered', /₹[\d,]/.test(text) || /Rs/.test(text)],
    ['sidebar section', text.includes('Recovery Cases')],
  ]
  let ok = true
  for (const [name, pass] of checks) {
    console.log(`${pass ? 'ok  ' : 'FAIL'} ${name}`)
    if (!pass) ok = false
  }
  if (bootError) { console.log('BOOT ERROR:', String(bootError).slice(0, 200)); ok = false }
  const rootHtml = window.document.getElementById('root').innerHTML.length
  console.log(`rendered DOM size: ${rootHtml} chars`)
  console.log(ok ? '\nBROWSER BOOT: SUCCESS — control center renders with live data'
                 : '\nBROWSER BOOT: FAILED')
  process.exit(ok ? 0 : 1)
}, 4000)
