'use strict';

const test = require('node:test');
const assert = require('node:assert');
const { Readable, Writable } = require('node:stream');
const fw = require('../index.js');

function sink() {
  const chunks = [];
  const w = new Writable({
    write(chunk, _enc, cb) { chunks.push(Buffer.from(chunk)); cb(); },
  });
  w.collected = () => Buffer.concat(chunks);
  return w;
}

test('encode/decode roundtrip', () => {
  const value = { a: 1, b: [1, 2, 3], c: { nested: true }, s: 'héllo " world' };
  assert.deepStrictEqual(fw.decode(fw.encode(value)), value);
});

test('encode is byte-compatible with JSON.stringify', () => {
  const value = { x: [1, 2, 3], y: 'text' };
  assert.strictEqual(fw.encode(value).toString('utf8'), JSON.stringify(value));
});

test('encodeArray then decodeArray roundtrips', async () => {
  const items = Array.from({ length: 1000 }, (_, i) => ({ id: i, name: `row-${i}`, ok: i % 2 === 0 }));
  const w = sink();
  const n = await fw.encodeArray(items, w);
  assert.strictEqual(n, 1000);
  // Valid ordinary JSON array.
  assert.deepStrictEqual(JSON.parse(w.collected().toString('utf8')), items);
  // Lazy decode yields the same elements.
  const out = [];
  for await (const el of fw.decodeArray(Readable.from(w.collected()))) out.push(el);
  assert.deepStrictEqual(out, items);
});

test('decodeArray handles nested structures, commas and brackets in strings', async () => {
  const tricky = [
    { s: 'has, comma and ] bracket and " quote' },
    [1, [2, 3], { k: 'v,][' }],
    'plain',
    42,
    null,
  ];
  const out = [];
  for await (const el of fw.decodeArray(Readable.from(fw.encode(tricky)))) out.push(el);
  assert.deepStrictEqual(out, tricky);
});

test('encodeArray accepts an async iterable', async () => {
  async function* gen() { for (let i = 0; i < 5; i++) yield { i }; }
  const w = sink();
  const n = await fw.encodeArray(gen(), w);
  assert.strictEqual(n, 5);
  assert.deepStrictEqual(JSON.parse(w.collected().toString('utf8')), [0, 1, 2, 3, 4].map((i) => ({ i })));
});

test('decodeArray works across many small chunks (multi-chunk streaming)', async () => {
  const items = Array.from({ length: 5000 }, (_, i) => ({ id: i, name: `row-${i}`, ok: i % 2 === 0 }));
  const bytes = fw.encode(items);
  // Emit the payload in tiny 64-byte chunks to force element boundaries to land
  // mid-chunk repeatedly - the case that broke a naive rescanning parser.
  function* smallChunks() {
    for (let i = 0; i < bytes.length; i += 64) yield bytes.subarray(i, i + 64);
  }
  const out = [];
  for await (const el of fw.decodeArray(Readable.from(smallChunks()))) out.push(el);
  assert.deepStrictEqual(out, items);
});

test('decodeArray rejects a non-array', async () => {
  await assert.rejects(async () => {
    for await (const _ of fw.decodeArray(Readable.from(Buffer.from('{"not":"array"}')))) { /* */ }
  });
});

test('decodeArray enforces maxDepth against deeply nested input', async () => {
  const inner = '['.repeat(300) + '0' + ']'.repeat(300);
  const payload = Buffer.from('[' + inner + ']');
  await assert.rejects(async () => {
    for await (const _ of fw.decodeArray(Readable.from(payload), { maxDepth: 200 })) { /* */ }
  }, /nesting depth/);
});

test('decodeArray handles multibyte UTF-8 split across chunk boundaries', async () => {
  const items = Array.from({ length: 500 }, (_, i) => ({ text: `unïcode ✓ with €uros and 🎯 ${i}` }));
  const bytes = fw.encode(items);
  // 5-byte chunks guarantee boundaries land inside multibyte sequences.
  function* tiny() { for (let i = 0; i < bytes.length; i += 5) yield bytes.subarray(i, i + 5); }
  const out = [];
  for await (const el of fw.decodeArray(Readable.from(tiny()))) out.push(el);
  assert.deepStrictEqual(out, items);
});

test('XML encodeArray/decodeArray round-trips with types preserved', async () => {
  const items = [
    { id: 1, name: 'row-1', ok: true, tags: ['a', 'b'], score: 3.5, note: null },
    { id: 2, name: 'has < & > " chars', ok: false, nested: { x: [1, 2, { y: 'z' }] } },
    42, 'plain', [1, 2, 3], null, true,
  ];
  const w = sink();
  const n = await fw.encodeArray(items, w, { format: 'xml' });
  assert.strictEqual(n, items.length);
  const out = [];
  for await (const el of fw.decodeArray(Readable.from(w.collected()), { format: 'xml' })) out.push(el);
  assert.deepStrictEqual(out, items);
});

test('XML decodeArray works across tiny chunks (multi-chunk streaming)', async () => {
  const items = Array.from({ length: 2000 }, (_, i) => ({ id: i, name: `row-${i}`, ok: i % 2 === 0, vals: [i, i + 1] }));
  const w = sink();
  await fw.encodeArray(items, w, { format: 'xml' });
  const bytes = w.collected();
  function* tiny() { for (let i = 0; i < bytes.length; i += 7) yield bytes.subarray(i, i + 7); }
  const out = [];
  for await (const el of fw.decodeArray(Readable.from(tiny()), { format: 'xml' })) out.push(el);
  assert.deepStrictEqual(out, items);
});

test('XML custom root tag', async () => {
  const w = sink();
  await fw.encodeArray([{ a: 1 }, { a: 2 }], w, { format: 'xml', root: 'records' });
  assert.ok(w.collected().toString('utf8').startsWith('<?xml version="1.0" encoding="UTF-8"?><records>'));
});

test('unknown format throws', async () => {
  const w = sink();
  await assert.rejects(async () => { await fw.encodeArray([1], w, { format: 'yaml' }); });
});

test('encodeArray honors writer backpressure (slow consumer throttles producer)', async () => {
  // A writable with a tiny highWaterMark that drains slowly. If flatwire respects
  // backpressure, the producer pauses and the number of in-flight (unacked)
  // chunks stays small instead of the whole array buffering up.
  const { Writable } = require('node:stream');
  let buffered = 0;
  let maxBuffered = 0;
  const slow = new Writable({
    highWaterMark: 16,
    write(_chunk, _enc, cb) {
      buffered++; maxBuffered = Math.max(maxBuffered, buffered);
      setTimeout(() => { buffered--; cb(); }, 0); // drain asynchronously
    },
  });
  const items = Array.from({ length: 500 }, (_, i) => ({ id: i, payload: 'x'.repeat(64) }));
  await fw.encodeArray(items, slow, { format: 'msgpack' });
  // With backpressure honored, only a bounded number of chunks are ever in flight.
  assert.ok(maxBuffered <= 5, `expected bounded in-flight chunks, saw ${maxBuffered}`);
});

test('encodeArray can be cancelled mid-stream with an AbortSignal', async () => {
  const ac = new AbortController();
  let produced = 0;
  function* rows() {
    for (let i = 0; i < 1000; i++) { produced++; if (i === 10) ac.abort(); yield { id: i }; }
  }
  const w = sink();
  await assert.rejects(
    () => fw.encodeArray(rows(), w, { format: 'json', signal: ac.signal }),
    (e) => e.name === 'AbortError');
  // Production stopped promptly after the abort, not after all 1000 rows.
  assert.ok(produced < 100, `expected early stop, produced ${produced}`);
});

test('msgpack encodeArray/decodeArray round-trips with types', async () => {
  const items = [
    { id: 1, name: 'row-1', ok: true, tags: ['a', 'b'], score: 3.5, note: null },
    42, -7, 300, -300, 100000, 'unïcode ✓ €uro 🎯', [1, 2, 3], null, true, 3.14159, -1.5,
  ];
  const w = sink();
  const n = await fw.encodeArray(items, w, { format: 'msgpack' });
  assert.strictEqual(n, items.length);
  const out = [];
  for await (const el of fw.decodeArray(Readable.from(w.collected()), { format: 'msgpack' })) out.push(el);
  assert.deepStrictEqual(out, items);
});

test('msgpack is more compact than JSON', async () => {
  const items = Array.from({ length: 1000 }, (_, i) => ({ id: i, name: `row-${i}`, ok: i % 2 === 0 }));
  const jw = sink(); await fw.encodeArray(items, jw, { format: 'json' });
  const mw = sink(); await fw.encodeArray(items, mw, { format: 'msgpack' });
  assert.ok(mw.collected().length < jw.collected().length);
});

test('msgpack decodes across tiny chunks', async () => {
  const items = Array.from({ length: 2000 }, (_, i) => ({ id: i, vals: [i, i + 1, i + 2] }));
  const w = sink();
  await fw.encodeArray(items, w, { format: 'msgpack' });
  const bytes = w.collected();
  function* tiny() { for (let i = 0; i < bytes.length; i += 5) yield bytes.subarray(i, i + 5); }
  const out = [];
  for await (const el of fw.decodeArray(Readable.from(tiny()), { format: 'msgpack' })) out.push(el);
  assert.deepStrictEqual(out, items);
});
