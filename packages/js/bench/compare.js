'use strict';

// Head-to-head Node benchmark: built-in JSON vs flatwire, measuring peak memory
// the only reliable way in Node - peak RSS of an isolated child process running
// exactly one operation (process.resourceUsage().maxRSS, KB). In-process
// heapUsed polling is unreliable (V8 GC timing dominates; no per-op allocation
// counter like Python's tracemalloc).
//
// The decode/aggregate input is a real on-disk JSON file so the streaming case
// does NOT secretly hold the source array in memory - that is the only setup in
// which flatwire's flat-memory claim is meaningful (input arrives from a
// file/socket, not an array you already materialized).
//
// Run:  node bench/compare.js

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { Writable } = require('node:stream');
const { spawnSync } = require('node:child_process');
const fw = require('../index.js');

function makeRecords(n) {
  const out = new Array(n);
  for (let i = 0; i < n; i++) out[i] = { id: i, name: `row-${i}`, payload: 'x'.repeat(200), ok: i % 2 === 0 };
  return out;
}

function nullSink() {
  return new Writable({ write(_c, _e, cb) { cb(); } });
}

async function runScenario(scn, arg) {
  const t0 = process.hrtime.bigint();

  if (scn === 'agg_whole') {
    // Read the whole file into memory, parse, aggregate. Peak = file + objects.
    const buf = fs.readFileSync(arg);
    let t = 0; for (const r of JSON.parse(buf.toString('utf8'))) t += r.id; if (t < 0) throw 0;
  } else if (scn === 'agg_stream') {
    // Stream the file from disk, one element at a time. Peak = one chunk + one
    // element - never the whole file.
    let t = 0;
    for await (const r of fw.decodeArray(fs.createReadStream(arg, { highWaterMark: 65536 }))) t += r.id;
    if (t < 0) throw 0;
  } else {
    throw new Error('unknown scenario ' + scn);
  }

  const timeMs = Number(process.hrtime.bigint() - t0) / 1e6;
  process.stdout.write(JSON.stringify({ maxRSS_kb: process.resourceUsage().maxRSS, time_ms: timeMs }));
}

function measure(scn, arg) {
  let bestRss = Infinity;
  let bestTime = Infinity;
  for (let i = 0; i < 3; i++) {
    const r = spawnSync(process.execPath, [__filename, '--worker', scn, String(arg)], { encoding: 'utf8' });
    if (r.status !== 0) { console.error(r.stderr); throw new Error('worker failed'); }
    const out = JSON.parse(r.stdout);
    bestRss = Math.min(bestRss, out.maxRSS_kb);
    bestTime = Math.min(bestTime, out.time_ms);
  }
  return { rss_kb: bestRss, time_ms: bestTime };
}

function humanKb(kb) {
  let n = kb * 1024;
  const u = ['B', 'KB', 'MB', 'GB'];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return `${i === 0 ? n.toFixed(0) : n.toFixed(1)}${u[i]}`;
}

function humanBytes(n) {
  const u = ['B', 'KB', 'MB', 'GB'];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return `${i === 0 ? n.toFixed(0) : n.toFixed(1)}${u[i]}`;
}

async function main() {
  const rows = [];
  for (const n of [1000, 10000, 50000]) {
    const blob = fw.encode(makeRecords(n));
    const size = blob.length;
    const file = path.join(os.tmpdir(), `flatwire-bench-${n}.json`);
    fs.writeFileSync(file, blob);

    rows.push({
      elements: n,
      payload_bytes: size,
      agg_whole: measure('agg_whole', file),
      agg_stream: measure('agg_stream', file),
    });
    fs.unlinkSync(file);
    console.log(`[records n=${n} ~${humanBytes(size)}] done`);
  }

  const dir = path.join(__dirname, 'results');
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, 'comparison.json'), JSON.stringify({ node: process.version, note: 'peak RSS in KB, isolated child processes (~48MB Node runtime baseline included); decode reads from an on-disk file', rows }, null, 2));

  console.log('\n=== decode-and-aggregate from disk: peak process RSS (~48MB Node baseline included) ===');
  console.log(`${'elements'.padStart(9)} ${'payload'.padStart(9)} ${'read+parse'.padStart(12)} ${'flatwire stream'.padStart(16)}`);
  for (const r of rows) {
    console.log(`${String(r.elements).padStart(9)} ${humanBytes(r.payload_bytes).padStart(9)} ` +
      `${humanKb(r.agg_whole.rss_kb).padStart(12)} ${humanKb(r.agg_stream.rss_kb).padStart(16)}`);
  }
  console.log('\n=== decode-and-aggregate time (ms; flatwire trades time for memory) ===');
  console.log(`${'elements'.padStart(9)} ${'read+parse'.padStart(12)} ${'flatwire stream'.padStart(16)}`);
  for (const r of rows) {
    console.log(`${String(r.elements).padStart(9)} ${r.agg_whole.time_ms.toFixed(2).padStart(12)} ${r.agg_stream.time_ms.toFixed(2).padStart(16)}`);
  }
}

if (process.argv[2] === '--worker') {
  runScenario(process.argv[3], process.argv[4]).catch((e) => { console.error(e); process.exit(1); });
} else {
  main();
}
