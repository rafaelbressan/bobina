# site: bobina.md

The website: the docs of the **latest bobina release**, for people and for agents. Astro, static output, no
client framework (a few hundred bytes of our own JavaScript per page, and Pagefind on /search/), no analytics.

```bash
cd site
npm ci                     # .npmrc pins the public registry
npm run dev                # http://localhost:4321
npm run build              # dist/: astro build, pagefind, then scripts/check.mjs
npm run capture            # after a release: record the casts and tickets again, then commit them
```

## Where the content comes from

Nothing is copied by hand. `scripts/release.mjs` runs before every build and decides which files the site shows:

- by default, the newest `vX.Y.Z` tag of the public repository (`git ls-remote`; pre-releases are skipped). Its
  files are extracted into `.release/tree/` with a private git index (`git fetch --depth=1` of that tag when the
  clone does not have it, as on Vercel and in CI, whose clones are shallow and have no tags; the GitHub tarball when
  there is no git at all);
- `BOBINA_SITE_REF=v0.1.0` (a tag, branch or commit) shows that one;
- `BOBINA_SITE_REF=WORKTREE` shows this checkout's files as they are: to work on docs before a release.

`src/content.config.ts` reads `README.md`, `CHANGELOG.md` and `docs/**/*.md` from there with Astro's glob
loader. `src/lib/site.ts` maps files to pages (`docs/CLI.md` → `/cli/`, `docs/problems/E107.md` →
`/problems/e107/`) and rewrites links: between docs they become site links, to other repository files GitHub
links at the release tag; images the docs show are copied to `/repo/`. So the site's own code changes on `main`
while what it describes stays the release. A release does not deploy by itself: commit the new captures (below),
and that push builds the site.

## For agents

- Every page has a twin with the same path plus `.md` (`/cli/` → `/cli.md`, `/` → `/index.md`, the README):
  the release's Markdown file with its links pointing at other twins. Each page names it in
  `<link rel="alternate" type="text/markdown">` and has "Copy for AI" (with JS) and "View as Markdown".
- `Accept: text/markdown` on a page answers its twin: `routes` with a `has` header condition in `../vercel.json`,
  because Vercel serves an existing file before any rewrite.
- `/llms.txt` and `/llms-full.txt` are the release's files (`llms-full.txt` is written by
  `tools/gen_llms_full.py`), with their links pointing at the twins.

## Casts and tickets

`capture/capture.py` installs the release from PyPI (`bobina==VERSION`, in `.capture-venv/`), runs real commands
on real files (`examples/` of the release and `site/examples/`) in a temporary folder with a `/dev/null` file
printer and a fixed date, and writes `src/captures/captures.json` (command lines, output as HTML, exit codes) and
`public/captures/*.png` (`bobina preview` of each file shown next to it). Nothing is drawn by hand. It stops when
an exit code is not the expected one or an output holds a home folder, a temporary path or a Bluetooth address.
The build stops when the captures are of another version than the release (`npm run capture` fixes it), and CI
records them again and compares (`.github/workflows/site.yml`).

Rendered here and committed rather than on Vercel: the build stays Node only, and the images are reviewed in the
pull request like the golden tests.

## Look

Thermal paper and 1-bit ink: torn (zigzag) edges, a light paper grain, no syntax colours. The tickets stay paper
in dark mode. Fonts are the ones bobina bundles (`capture/fonts.py` copies them as WOFF2, unchanged, with their
licenses into `public/fonts/`): Atkinson Hyperlegible for text, Spleen 12×24 (the printer's own font in previews)
for titles, Terminus for code and terminals. The printing animation is CSS (`steps()`, one step per 24-dot line);
a few lines of JS start it once, when it is seen. With reduced motion or without JS everything is simply there.

## Checks (`scripts/check.mjs`)

Every page has its twin and announces it; every internal link, anchor and image resolves (HTML, twins, llms
files); every page path with `Accept: text/markdown` is routed by `vercel.json` to a twin that exists, and assets
are not; no personal home folder or real Bluetooth address; no page over the JavaScript budget.

## Vercel

`../vercel.json` holds the whole configuration (install, build, output directory, routes, headers); there is no
token in the repository. To connect it once: Vercel → Add New → Project → import `rafaelbressan/bobina` (keep
the Root Directory at the repository root; vercel.json sets the rest) → Deploy. Then Settings → Domains → add
`bobina.md` (and `www.bobina.md`, redirecting to it) and set the DNS records Vercel shows at the registrar.
