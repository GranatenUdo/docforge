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
