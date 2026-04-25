# docforge microsite

The public-facing documentation site for [docforge](https://github.com/GranatenUdo/docforge), deployed to GitHub Pages at <https://GranatenUdo.github.io/docforge/>.

Built with [Astro](https://astro.build) + [Starlight](https://starlight.astro.build).

## Develop locally

```bash
pnpm install
pnpm run dev        # http://localhost:4321/docforge/
```

## Build

```bash
pnpm run build
```

Output lands in `dist/`.

## Deploy

Automatic via [`.github/workflows/microsite.yml`](../.github/workflows/microsite.yml) on every `master` push that touches `microsite/**`.

## Notes for Windows developers

npm on Windows has a [known bug](https://github.com/npm/cli/issues/4828) where native optional dependencies (`@rollup/rollup-win32-x64-msvc`) fail to install. **Use `pnpm` instead** — it handles native binaries reliably. Linux CI is unaffected either way.

## Asset sources

Canonical visual assets (logo, favicon, architecture diagram, social preview) live in `docs/assets/` at the repo root. The `microsite/scripts/sync-assets.mjs` prebuild step copies them into `microsite/public/` before each `astro dev` or `astro build` run, so nothing in `public/assets/` or the favicon files at `public/` root needs to be edited or committed.

**One exception:** `microsite/src/assets/logo.svg` is a duplicate of `docs/assets/logo.svg` that lives inside the Astro project source. Starlight's `astro.config.mjs` `logo` config requires the file under `src/assets/`, and Astro's image pipeline can't follow symlinks across the project boundary. Keep this file in sync with the canonical when the logo changes.
