import { defineConfig } from 'astro/config';
import { satteri } from '@astrojs/markdown-satteri';
import { copyFileSync, mkdirSync, readdirSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { linksPlugin } from './src/lib/links-plugin.ts';
import { TREE } from './src/lib/site.ts';

/** Images the docs show (examples/*.png, spec/conformance/*.png) are copied from the release to /repo/. */
function repoImages() {
  return {
    name: 'bobina-repo-images',
    hooks: {
      'astro:build:done': ({ dir }) => {
        const out = fileURLToPath(dir);
        const wanted = new Set();
        const walk = (d) => {
          for (const f of readdirSync(d, { withFileTypes: true })) {
            const p = join(d, f.name);
            if (f.isDirectory()) walk(p);
            else if (/\.(html|md|txt)$/.test(f.name))
              for (const m of readFileSync(p, 'utf8').matchAll(/\/repo\/([\w./-]+\.(?:png|jpe?g|svg|gif))/g)) wanted.add(m[1]);
          }
        };
        walk(out);
        for (const rel of wanted) {
          mkdirSync(dirname(join(out, 'repo', rel)), { recursive: true });
          copyFileSync(join(TREE, rel), join(out, 'repo', rel));
        }
      },
    },
  };
}

export default defineConfig({
  site: process.env.BOBINA_SITE_URL || 'https://bobina.md',
  output: 'static',
  trailingSlash: 'ignore',
  build: { format: 'directory', inlineStylesheets: 'auto' },
  devToolbar: { enabled: false },
  integrations: [repoImages()],
  markdown: {
    syntaxHighlight: false, // a 1-bit printer, a 1-bit site: code is ink on paper
    processor: satteri({
      features: { smartPunctuation: false }, // `--yes` must stay two hyphens
      mdastPlugins: [linksPlugin],
    }),
  },
});
