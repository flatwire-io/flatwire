'use strict';

// flatwire - streaming JSON serialization that keeps memory flat and time linear.
// Zero dependencies: built on JSON plus a hand-written streaming array scanner
// that finds element boundaries without materializing the whole collection.

const COMMA = Buffer.from(',');
const OPEN = Buffer.from('[');
const CLOSE = Buffer.from(']');

function encode(value) {
  return Buffer.from(JSON.stringify(value), 'utf8');
}

function decode(data) {
  const text = Buffer.isBuffer(data) ? data.toString('utf8') : data;
  return JSON.parse(text);
}

// Write helper that respects backpressure.
function write(writable, chunk) {
  return new Promise((resolve, reject) => {
    writable.write(chunk, (err) => (err ? reject(err) : resolve()));
  });
}

async function encodeTo(value, writable) {
  // For a single value we hand off one buffer; the streaming win is in
  // encodeArray, where memory stays bounded by one element.
  await write(writable, encode(value));
}

async function decodeFrom(readable) {
  const chunks = [];
  for await (const c of readable) chunks.push(c);
  return decode(Buffer.concat(chunks));
}

// Stream a large collection as a JSON array, one element at a time. Accepts any
// sync or async iterable. Peak memory is bounded by the largest single element.
async function encodeArray(items, writable) {
  await write(writable, OPEN);
  let count = 0;
  for await (const item of items) {
    if (count) await write(writable, COMMA);
    await write(writable, Buffer.from(JSON.stringify(item), 'utf8'));
    count += 1;
  }
  await write(writable, CLOSE);
  return count;
}

// Lazily parse a top-level JSON array from a readable, yielding one element at a
// time. Mirrors the Python scanner: a persistent cursor tracks bracket/brace
// depth and string state to find the depth-1 commas that separate elements,
// without ever rescanning bytes across chunk boundaries. `maxDepth` bounds how
// deeply a single element may nest before the input is rejected (0 disables it).
async function* decodeArray(readable, { maxDepth = 200 } = {}) {
  let buf = '';
  let pos = 0;           // persistent scan cursor - never rescans prior bytes
  let elemStart = 0;
  let depth = 0;
  let inString = false;
  let escape = false;
  let started = false;

  for await (const chunk of readable) {
    buf += Buffer.isBuffer(chunk) ? chunk.toString('utf8') : chunk;
    while (pos < buf.length) {
      const ch = buf[pos];
      if (!started) {
        if (ch === ' ' || ch === '\n' || ch === '\t' || ch === '\r') { pos += 1; elemStart = pos; continue; }
        if (ch !== '[') throw new Error('decodeArray expects a top-level JSON array');
        started = true;
        pos += 1;
        elemStart = pos;
        continue;
      }
      if (inString) {
        if (escape) escape = false;
        else if (ch === '\\') escape = true;
        else if (ch === '"') inString = false;
        pos += 1;
        continue;
      }
      if (ch === '"') { inString = true; pos += 1; }
      else if (ch === '{' || ch === '[') {
        depth += 1;
        if (maxDepth && depth > maxDepth) throw new Error(`decodeArray: nesting depth exceeded ${maxDepth}`);
        pos += 1;
      }
      else if (ch === '}' || ch === ']') {
        if (ch === ']' && depth === 0) {
          const seg = buf.slice(elemStart, pos).trim();
          if (seg) yield JSON.parse(seg);
          return;
        }
        depth -= 1;
        pos += 1;
      } else if (ch === ',' && depth === 0) {
        const seg = buf.slice(elemStart, pos).trim();
        if (seg) yield JSON.parse(seg);
        pos += 1;
        // Drop consumed prefix so the buffer never grows with the array.
        buf = buf.slice(pos);
        pos = 0;
        elemStart = 0;
      } else {
        pos += 1;
      }
    }
  }
  throw new Error('stream ended before the JSON array was closed');
}

module.exports = { encode, decode, encodeTo, decodeFrom, encodeArray, decodeArray };
