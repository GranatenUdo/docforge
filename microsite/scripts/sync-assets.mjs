#!/usr/bin/env node
// Copy canonical assets from ../docs/assets/ into microsite/public/.
//
// Source of truth: docs/assets/
// Destination:     microsite/public/
//
// Run automatically before `astro dev` and `astro build` via package.json.

import { mkdir, copyFile, readdir } from 'node:fs/promises';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const docsAssets = join(here, '..', '..', 'docs', 'assets');
const publicDir = join(here, '..', 'public');

async function ensureDir(path) {
  await mkdir(path, { recursive: true });
}

async function copyToplevelAssets() {
  // Logo, diagram, social preview → public/assets/
  const dest = join(publicDir, 'assets');
  await ensureDir(dest);
  const entries = await readdir(docsAssets, { withFileTypes: true });
  for (const entry of entries) {
    if (entry.isFile()) {
      await copyFile(join(docsAssets, entry.name), join(dest, entry.name));
    }
  }
}

async function copyFavicons() {
  // docs/assets/favicon/* → public/ (root, so /favicon.ico resolves).
  const src = join(docsAssets, 'favicon');
  const entries = await readdir(src, { withFileTypes: true });
  for (const entry of entries) {
    if (entry.isFile()) {
      await copyFile(join(src, entry.name), join(publicDir, entry.name));
    }
  }
}

async function main() {
  await ensureDir(publicDir);
  await copyToplevelAssets();
  await copyFavicons();
  console.log(`sync-assets: copied from ${docsAssets} → ${publicDir}`);
}

main().catch((err) => {
  console.error('sync-assets failed:', err);
  process.exit(1);
});
