/* Pure in-process build: tsc → rollup → tailwindcss.
 * Avoids esbuild/rolldown worker spawns that the sandbox blocks (spawn EPERM). */
const { rollup } = require('rollup')
const { nodeResolve } = require('@rollup/plugin-node-resolve')
const commonjs = require('@rollup/plugin-commonjs')
const fs = require('fs')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')
const BUILD = path.join(ROOT, '.build')
const DIST = path.join(ROOT, 'dist')

function run(cmd, args, opts = {}) {
  const { spawnSync } = require('child_process')
  const r = spawnSync(cmd, args, { stdio: 'inherit', ...opts, shell: false })
  if (r.status !== 0) throw new Error(`${cmd} ${args.join(' ')} failed with ${r.status}`)
}

const NODE = process.execPath
const TSC = path.join(ROOT, 'node_modules', 'typescript', 'bin', 'tsc')
const TW = path.join(ROOT, 'node_modules', '@tailwindcss', 'cli', 'dist', 'index.mjs')

async function main() {
  // 1. clean
  fs.rmSync(BUILD, { recursive: true, force: true })
  fs.rmSync(DIST, { recursive: true, force: true })

  // 2. tsc emit (compiler is pure JS)
  run(NODE, [TSC, '-p', 'tsconfig.emit.json'], { cwd: ROOT })

  // 3. tailwind (native binding loads in-process)
  run(NODE, [TW, '-i', 'src/index.css', '-o', 'dist/assets/app.css'], { cwd: ROOT })

  // 4. rollup bundle (native binding loads in-process)
  const ignoreCss = {
    name: 'ignore-css',
    resolveId(source) {
      if (source.endsWith('.css')) return '\0virtual-empty-css'
      return null
    },
    load(id) {
      if (id === '\0virtual-empty-css') return ''
      return null
    },
  }
  const bundle = await rollup({
    input: path.join(BUILD, 'main.js'),
    plugins: [ignoreCss, commonjs(), nodeResolve({ preferBuiltins: false })],
    onwarn: () => { /* suppress eval warnings from recharts deps */ },
  })
  await bundle.write({
    dir: path.join(DIST, 'assets'),
    entryFileNames: 'app.js',
    format: 'esm',
    sourcemap: false,
  })
  await bundle.close()

  // 5. index.html
  const html = `<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Revenue Guard — AI Revenue Recovery</title>
    <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'><text y='14' font-size='14'>🛡</text></svg>" />
    <link rel="stylesheet" href="./assets/app.css" />
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="./assets/app.js"></script>
  </body>
</html>
`
  fs.writeFileSync(path.join(DIST, 'index.html'), html)
  const kb = (fs.statSync(path.join(DIST, 'assets/app.js')).size / 1024).toFixed(0)
  console.log(`build ok: dist/index.html + dist/assets/app.js (${kb} KB) + app.css`)
}

main().catch(e => { console.error(e); process.exit(1) })
