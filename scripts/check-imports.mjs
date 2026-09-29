/**
 * Guard: the Hermes desktop runtime loader REFUSES any import outside
 * `@hermes/plugin-sdk` and `react*`.
 *
 * From apps/desktop/src/contrib/runtime-loader.ts:
 *   "a relative path cannot resolve against the blob: base the module is
 *    evaluated from"  →  `unsupported import(s): … runtime plugins may only
 *    import @hermes/plugin-sdk and react`
 *
 * A plugin that imports `./lib/foo.mjs` therefore fails to load and the whole
 * UI surface (the 🎭 Personas / 🎙️ Studio titlebar controls) silently
 * disappears. This script checks the DEPLOYED plugin.js the way the loader
 * does, so the failure is caught offline instead of as a missing button.
 *
 * Run: node scripts/check-imports.mjs [path/to/plugin.js]
 */
import { readFileSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const repo = resolve(here, '..')

/** Same specifier pattern the runtime loader uses. */
const IMPORT_RE = /(?:from\s*|import\s*\(\s*|import\s+)(['"])([^'"]+)\1/g

const ALLOWED_PREFIXES = ['@hermes/plugin-sdk', 'react']

function isAllowed(spec) {
  return ALLOWED_PREFIXES.some((p) => spec === p || spec.startsWith(p + '/'))
}

const targets = process.argv.slice(2)
if (!targets.length) {
  targets.push(resolve(repo, 'desktop/plugin.js'))
}

let failed = false

for (const target of targets) {
  const path = resolve(target)
  let source
  try {
    source = readFileSync(path, 'utf8')
  } catch (err) {
    console.error(`✗ ${path}\n  cannot read: ${err.message}`)
    failed = true
    continue
  }

  const specs = new Set()
  for (const m of source.matchAll(IMPORT_RE)) {
    if (m[2]) specs.add(m[2])
  }

  const unsupported = [...specs].filter((s) => !isAllowed(s)).sort()

  if (unsupported.length) {
    failed = true
    console.error(`✗ ${path}`)
    console.error(`  unsupported import(s): ${unsupported.join(', ')}`)
    console.error('  The desktop runtime loader only allows @hermes/plugin-sdk and react*.')
    console.error('  A relative import cannot resolve (the module is evaluated from a Blob),')
    console.error('  so the plugin will NOT load and its UI surfaces will vanish.')
    console.error('  Run `npm run build:plugin` to inline the helpers into a single file.')
  } else {
    console.log(`✓ ${path}`)
    console.log(`  imports: ${[...specs].sort().join(', ') || '(none)'}`)
  }
}

if (failed) {
  console.error('\nFAILED: at least one plugin.js would be refused by the desktop loader.')
  process.exit(1)
}
console.log('\nAll plugin.js files pass the desktop import allowlist.')
