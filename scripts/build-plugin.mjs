/**
 * Build: inline `desktop/lib/*.mjs` into a single self-contained
 * `desktop/dist/plugin.js`.
 *
 * WHY THIS EXISTS — the Hermes desktop runtime loader evaluates a runtime
 * plugin from a Blob URL and refuses every import outside
 * `@hermes/plugin-sdk` / `react*`. A relative `./lib/…` import cannot resolve
 * against a Blob base, so shipping the multi-file form means the plugin
 * silently fails to load and the 🎭 Personas / 🎙️ Studio titlebar controls
 * disappear from the app.
 *
 * So: `desktop/lib/persona-helpers.mjs` stays the real, importable,
 * unit-testable source; this script produces the shipped artifact by
 * stripping the `export` keywords and prepending the helper bodies. The
 * result is ONE file with no relative imports, byte-for-byte equivalent in
 * behaviour.
 *
 * Run: node scripts/build-plugin.mjs
 */
import { readFileSync, writeFileSync, mkdirSync, statSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const repo = resolve(here, '..')

const LIB_DIR = resolve(repo, 'desktop/lib')
const SRC_PLUGIN = resolve(repo, 'desktop/plugin.src.js')
const SRC_ENTRY = resolve(repo, 'desktop/plugin.js')
const OUT_DIR = resolve(repo, 'desktop/dist')
const OUT_FILE = resolve(OUT_DIR, 'plugin.js')

/**
 * The source of truth for the plugin. It may either:
 *   - `import … from './lib/persona-helpers.mjs'`  (development form, inlined
 *     here), or
 *   - already be self-contained (already-inlined form), in which case the
 *     helpers are prepended only if they are not already present.
 */
const entry = readFileSync(SRC_ENTRY, 'utf8')

const IMPORT_BLOCK_RE = /import\s*\{[\s\S]*?\}\s*from\s*['"]\.\/lib\/persona-helpers\.mjs['"];?/
const hasRelativeLibImport = IMPORT_BLOCK_RE.test(entry)

let helpersSource = ''
if (hasRelativeLibImport) {
  const libFile = resolve(LIB_DIR, 'persona-helpers.mjs')
  helpersSource = readFileSync(libFile, 'utf8')
}

if (!helpersSource) {
  // No lib import: either already built, or the plugin has no helpers.
  const alreadyInline = /function\s+characterStrengthPercent\s*\(/.test(entry)
  if (alreadyInline) {
    console.log('plugin.js is already self-contained (helpers inlined). Nothing to do.')
    mkdirSync(OUT_DIR, { recursive: true })
    writeFileSync(OUT_FILE, entry)
    console.log(`wrote ${OUT_FILE} (${statSync(OUT_FILE).size} bytes)`)
    process.exit(0)
  }
  console.error('No ./lib import and no inlined helpers found — refusing to guess.')
  process.exit(1)
}

// Strip the ESM export keywords — the shipped file is a classic script that
// the Blob loader can evaluate on its own.
const inlinedHelpers = helpersSource
  .replace(/^export\s+(function|const|let|var|class)\s/gm, '$1 ')
  .replace(/^export\s*\{[^}]*\}\s*;?\s*$/gm, '')

const banner = `/**
 * GENERATED FILE — do not edit.
 * Built by scripts/build-plugin.mjs from desktop/plugin.js + desktop/lib/persona-helpers.mjs.
 *
 * The Hermes desktop runtime loader evaluates plugins from a Blob URL and
 * allows only @hermes/plugin-sdk and react* imports, so the helpers must be
 * inlined here. Edit desktop/lib/persona-helpers.mjs and desktop/plugin.js,
 * then re-run the build.
 */`

let out = entry.replace(IMPORT_BLOCK_RE, `${banner}\n\n${inlinedHelpers}`)

// Belt and braces: the output must not import anything relative.
const leftover = out.match(/(?:from\s*|import\s*\(\s*|import\s+)(['"])(\.[^'"]*)\1/)
if (leftover) {
  console.error(`Build failed: output still contains a relative import: ${leftover[2]}`)
  process.exit(1)
}

mkdirSync(OUT_DIR, { recursive: true })
writeFileSync(OUT_FILE, out)
console.log(`wrote ${OUT_FILE} (${statSync(OUT_FILE).size} bytes)`)
console.log('relative imports in output: 0')
