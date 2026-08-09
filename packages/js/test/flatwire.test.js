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
