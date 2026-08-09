'use strict';

// flatwire conformance runner (Node). Mirrors run.py: encode+decode every case
// in every format, record round-trip and a SHA-256 of the encoded bytes.

const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { Readable, Writable } = require('node:stream');

const ROOT = path.resolve(__dirname, '..');
const fw = require(path.join(ROOT, '..', 'packages', 'js', 'index.js'));

const FORMATS = ['json', 'xml', 'msgpack'];

function sink() {
  const chunks = [];
  const w = new Writable({ write(c, _e, cb) { chunks.push(Buffer.from(c)); cb(); } });
  w.collected = () => Buffer.concat(chunks);
  return w;
}

// Structural deep-equal that treats BigInt and Number consistently and handles
// the objects/arrays/scalars in the corpus.
function deepEqual(a, b) {
  if (a === b) return true;
  if (typeof a === 'bigint' || typeof b === 'bigint') return String(a) === String(b);
  if (a === null || b === null) return a === b;
  if (Array.isArray(a) && Array.isArray(b)) {
    if (a.length !== b.length) return false;
    return a.every((x, i) => deepEqual(x, b[i]));
  }
  if (typeof a === 'object' && typeof b === 'object') {
    const ka = Object.keys(a), kb = Object.keys(b);
    if (ka.length !== kb.length) return false;
    return ka.every((k) => Object.prototype.hasOwnProperty.call(b, k) && deepEqual(a[k], b[k]));
  }
  if (typeof a === 'number' && typeof b === 'number') {
    return a === b || (Number.isNaN(a) && Number.isNaN(b));
  }
  return false;
}

async function runCase(elements, fmt) {
  const w = sink();
  await fw.encodeArray(elements, w, { format: fmt });
  const data = w.collected();
  const out = [];
  for await (const el of fw.decodeArray(Readable.from(data), { format: fmt })) out.push(el);
  return { data, out };
}

async function main() {
  const corpus = JSON.parse(fs.readFileSync(path.join(ROOT, 'corpus.json'), 'utf8'));
  const results = { lang: 'node', tested_locally: true, cases: {} };
  for (const c of corpus.cases) {
    const entry = { tier: c.tier, formats: {} };
    for (const fmt of FORMATS) {
      try {
        const { data, out } = await runCase(c.elements, fmt);
        entry.formats[fmt] = {
          roundtrip: deepEqual(out, c.elements),
          sha256: crypto.createHash('sha256').update(data).digest('hex'),
          bytes: data.length,
        };
      } catch (e) {
        entry.formats[fmt] = { roundtrip: false, error: String(e && e.message || e) };
      }
    }
    results.cases[c.name] = entry;
  }
  const outPath = path.join(ROOT, 'results', 'node.json');
  fs.writeFileSync(outPath, JSON.stringify(results, null, 2));
  let passed = 0, total = 0;
  for (const c of Object.values(results.cases)) for (const f of Object.values(c.formats)) { total++; if (f.roundtrip) passed++; }
  console.log(`node conformance: ${passed}/${total} round-trip; wrote ${outPath}`);
}

main();
