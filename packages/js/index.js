'use strict';

// flatwire - streaming JSON serialization that keeps memory flat and time linear.
// Zero dependencies: built on JSON plus a hand-written streaming array scanner
// that finds element boundaries without materializing the whole collection.

const { StringDecoder } = require('node:string_decoder');

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

// Backpressure-aware write: honor the stream's highWaterMark. write() returns
// false when the internal buffer is full; we then wait for 'drain' before
// producing more, so a slow consumer throttles production instead of letting
// bytes pile up in the socket/file buffer. Rejects on stream 'error'.
function write(writable, chunk) {
  return new Promise((resolve, reject) => {
    const onError = (e) => { writable.removeListener('error', onError); reject(e); };
    writable.once('error', onError);
    const ok = writable.write(chunk);
    if (ok) {
      writable.removeListener('error', onError);
      resolve();
    } else {
      writable.once('drain', () => { writable.removeListener('error', onError); resolve(); });
    }
  });
}

function checkAborted(signal) {
  if (signal && signal.aborted) {
    const err = new Error('flatwire: stream aborted');
    err.name = 'AbortError';
    throw err;
  }
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

// Stream a large collection element-by-element. `opts.format` selects the wire
// format ("json" default, "xml", "msgpack"). `opts.signal` (an AbortSignal)
// cancels the stream mid-flight. Honors writer backpressure; peak memory is
// bounded by one element.
async function encodeArray(items, writable, opts = {}) {
  const format = opts.format || 'json';
  if (format === 'xml') return require('./xml.js').encodeArray(items, writable, opts);
  if (format === 'msgpack') return require('./msgpack.js').encodeArray(items, writable, opts);
  if (format !== 'json') throw new Error(`unknown format '${format}' (expected 'json', 'xml', or 'msgpack')`);
  const signal = opts.signal;
  checkAborted(signal);
  await write(writable, OPEN);
  let count = 0;
  for await (const item of items) {
    checkAborted(signal);
    if (count) await write(writable, COMMA);
    await write(writable, Buffer.from(JSON.stringify(item), 'utf8'));
    count += 1;
  }
  await write(writable, CLOSE);
  return count;
}

// Lazily parse a streamed collection, yielding one element at a time.
// `opts.format` selects "json" (default) or "xml".
function decodeArray(readable, opts = {}) {
  const format = opts.format || 'json';
  if (format === 'xml') return require('./xml.js').decodeArray(readable, opts);
  if (format === 'msgpack') return require('./msgpack.js').decodeArray(readable, opts);
  if (format !== 'json') throw new Error(`unknown format '${format}' (expected 'json', 'xml', or 'msgpack')`);
  return jsonDecodeArray(readable, opts);
}

// Lazily parse a top-level JSON array from a readable, yielding one element at a
// time. Mirrors the Python scanner: a persistent cursor tracks bracket/brace
// depth and string state to find the depth-1 commas that separate elements,
// without ever rescanning bytes across chunk boundaries. `maxDepth` bounds how
// deeply a single element may nest before the input is rejected (0 disables it).
async function* jsonDecodeArray(readable, { maxDepth = 200 } = {}) {
  let buf = '';
  let pos = 0;           // persistent scan cursor - never rescans prior bytes
  let elemStart = 0;
  let depth = 0;
  let inString = false;
  let escape = false;
  let started = false;

  // StringDecoder buffers any partial multibyte UTF-8 sequence that lands on a
  // chunk boundary, so splitting the stream mid-character is safe.
  const decoder = new StringDecoder('utf8');

  for await (const chunk of readable) {
    buf += Buffer.isBuffer(chunk) ? decoder.write(chunk) : chunk;
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

const MEDIA_TYPES = {
  json: 'application/json',
  xml: 'application/xml',
  msgpack: 'application/msgpack',
};

// One-line HTTP adapter: stream a large collection to an HTTP response (Node
// `http`/Express/Fastify — `res` is a Writable). Sets Content-Type from the
// format, streams with flat memory + backpressure, and ends the response.
// Returns the number of elements written.
//   app.get('/rows', async (req, res) => { await fw.sendArray(res, rows, { format: 'msgpack' }); });
async function sendArray(res, items, opts = {}) {
  const format = opts.format || 'json';
  if (typeof res.setHeader === 'function' && !res.headersSent) {
    res.setHeader('Content-Type', MEDIA_TYPES[format] || 'application/octet-stream');
  }
  const count = await encodeArray(items, res, opts);
  if (typeof res.end === 'function') res.end();
  return count;
}

const failure = require('./failure.js');

module.exports = {
  encode, decode, encodeTo, decodeFrom, encodeArray, decodeArray, sendArray, MEDIA_TYPES,
  encodeCheckedArray: failure.encodeCheckedArray,
  decodeCheckedArray: failure.decodeCheckedArray,
  StreamError: failure.StreamError,
  TruncatedStreamError: failure.TruncatedStreamError,
};
