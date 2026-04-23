#!/usr/bin/env node
// Upload images to Square Catalog and attach each one to a specific item variation.
//
// Usage (from the repo root):
//   SQUARE_ACCESS_TOKEN=xxx node scripts/upload-variant-images.mjs <folder>
//
// Defaults to production. To hit sandbox instead:
//   SQUARE_ACCESS_TOKEN=xxx SQUARE_ENV=sandbox node scripts/upload-variant-images.mjs <folder>
//
// The folder must contain a `mapping.json` file shaped like:
//   [
//     { "file": "black.jpg",    "variationId": "W5Y4Z...", "caption": "Black" },
//     { "file": "navy.jpg",     "variationId": "X8A2B...", "caption": "Navy", "isPrimary": true },
//     { "file": "heather.jpg",  "variationId": "K1P7Q..." }
//   ]
//
// - `file` is the image filename (jpg/png/gif, ≤15MB), relative to the folder.
// - `variationId` is the Square catalog object ID of the variation (NOT the item).
// - `caption` is optional; defaults to the filename stem.
// - `isPrimary: true` makes this the primary image for the variation. Optional.

import { readFile } from 'node:fs/promises';
import { resolve, join, basename, extname } from 'node:path';

const SQUARE_BASE = {
  sandbox:    'https://connect.squareupsandbox.com',
  production: 'https://connect.squareup.com',
};
const SQUARE_API_VERSION = '2025-01-23';

const folderArg = process.argv[2];
if (!folderArg) {
  console.error('usage: node scripts/upload-variant-images.mjs <folder>');
  process.exit(1);
}
const folder = resolve(folderArg);

const token = process.env.SQUARE_ACCESS_TOKEN;
if (!token) {
  console.error('error: SQUARE_ACCESS_TOKEN env var is required');
  console.error('  grab it from Square Developer Dashboard → your app → Credentials');
  process.exit(1);
}
const env = process.env.SQUARE_ENV || 'production';
const base = SQUARE_BASE[env];
if (!base) {
  console.error(`error: SQUARE_ENV must be "sandbox" or "production" (got "${env}")`);
  process.exit(1);
}

const mappingPath = join(folder, 'mapping.json');
let mapping;
try {
  mapping = JSON.parse(await readFile(mappingPath, 'utf8'));
} catch (err) {
  console.error(`error: could not read ${mappingPath}`);
  console.error(`  ${err.message}`);
  process.exit(1);
}
if (!Array.isArray(mapping) || mapping.length === 0) {
  console.error('error: mapping.json must be a non-empty array');
  process.exit(1);
}

console.log(`env:     ${env}`);
console.log(`folder:  ${folder}`);
console.log(`uploads: ${mapping.length}\n`);

let ok = 0, fail = 0;

for (const entry of mapping) {
  const { file, variationId, caption, isPrimary } = entry;
  const label = `${file || '?'} → ${variationId || '?'}`;

  if (!file || !variationId) {
    console.error(`  skip — entry missing file or variationId: ${JSON.stringify(entry)}`);
    fail++;
    continue;
  }

  const imagePath = join(folder, file);
  try {
    const bytes = await readFile(imagePath);
    const captionText = caption || basename(file, extname(file));

    const requestJson = {
      idempotency_key: crypto.randomUUID(),
      object_id: variationId,
      image: {
        type: 'IMAGE',
        id: '#new_image',
        image_data: {
          caption: captionText,
          name:    captionText,
        },
      },
    };

    const form = new FormData();
    form.append('request', JSON.stringify(requestJson));
    form.append('image_file', new Blob([bytes]), file);

    const url = `${base}/v2/catalog/images${isPrimary ? '?is_primary=true' : ''}`;
    const res = await fetch(url, {
      method: 'POST',
      headers: {
        'Square-Version': SQUARE_API_VERSION,
        'Authorization':  `Bearer ${token}`,
      },
      body: form,
    });

    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const errs = (data.errors || []).map(e => `${e.code}: ${e.detail || ''}`).join('; ');
      console.error(`  ✗ ${label}  [${res.status}] ${errs || JSON.stringify(data)}`);
      fail++;
    } else {
      const imgId = data.image?.id || data.catalog_object?.id || '?';
      console.log(`  ✓ ${label}  (image ${imgId})`);
      ok++;
    }
  } catch (err) {
    console.error(`  ✗ ${label}  ${err.message}`);
    fail++;
  }
}

console.log(`\ndone. ${ok} uploaded, ${fail} failed.`);
process.exit(fail > 0 ? 1 : 0);
