'use strict';

// Partial-stream failure semantics for flatwire (Node), matching the Python
// reference. A streamed collection is wrapped in an envelope whose terminal
// status is written LAST, so a consumer distinguishes clean completion, a
// producer error after N rows, and truncation:
//
//   {"items":[ e0, e1, ... ],"complete":true}
//   {"items":[ e0, e1, ... ],"complete":false,"error":{"message":"...","name":"..."}}
//
// See docs/FAILURE.md.

const { StringDecoder } = require('node:string_decoder');

class StreamError extends Error {
  constructor(error) {
    super(typeof error === 'object' && error && error.message ? error.message : String(error));
    this.name = 'StreamError';
    this.error = error;
  }
}
class TruncatedStreamError extends Error {
  constructor(msg) { super(msg || 'stream ended before a terminal status'); this.name = 'TruncatedStreamError'; }
}

function writeBackpressured(writable, chunk) {
  return new Promise((resolve, reject) => {
    const onError = (e) => { writable.removeListener('error', onError); reject(e); };
    writable.once('error', onError);
    const ok = writable.write(chunk);
    if (ok) { writable.removeListener('error', onError); resolve(); }
    else writable.once('drain', () => { writable.removeListener('error', onError); resolve(); });
  });
}

// Stream items inside a checked envelope. If iterating `items` throws, writes a
// complete:false trailer carrying the error, then re-throws. Returns the count.
async function encodeCheckedArray(items, writable) {
  await writeBackpressured(writable, Buffer.from('{"items":[', 'utf8'));
  let count = 0;
  try {
    for await (const item of items) {
      const prefix = count ? ',' : '';
      await writeBackpressured(writable, Buffer.from(prefix + JSON.stringify(item), 'utf8'));
      count += 1;
    }
  } catch (err) {
    const errObj = { message: err && err.message ? err.message : String(err), name: err && err.name ? err.name : 'Error' };
    await writeBackpressured(writable, Buffer.from('],"complete":false,"error":' + JSON.stringify(errObj) + '}', 'utf8'));
    throw err;
  }
  await writeBackpressured(writable, Buffer.from('],"complete":true}', 'utf8'));
  return count;
}

// Yield each item, then enforce the terminal status. Throws StreamError if the
// producer signalled complete:false, TruncatedStreamError if the stream ended
// without a terminal status.
async function* decodeCheckedArray(readable) {
  const decoder = new StringDecoder('utf8');
  let buf = '';
  let ended = false;
  const it = readable[Symbol.asyncIterator]();

  async function pull() {
    const { value, done } = await it.next();
    if (done) { ended = true; buf += decoder.end(); return false; }
    buf += Buffer.isBuffer(value) ? decoder.write(value) : String(value);
    return true;
  }

  const header = '{"items":[';
  while (buf.length < header.length) {
    if (!(await pull())) throw new TruncatedStreamError('stream ended before items array');
  }
  if (buf.slice(0, header.length) !== header) throw new Error('decodeCheckedArray: not a flatwire checked stream');
  let pos = header.length;
  let elemStart = pos;
  let depth = 0, inString = false, escape = false;

  for (;;) {
    while (pos < buf.length) {
      const ch = buf[pos];
      if (inString) {
        if (escape) escape = false;
        else if (ch === '\\') escape = true;
        else if (ch === '"') inString = false;
        pos += 1; continue;
      }
      if (ch === '"') { inString = true; pos += 1; }
      else if (ch === '{' || ch === '[') { depth += 1; pos += 1; }
      else if (ch === ']' && depth === 0) {
        const seg = buf.slice(elemStart, pos).trim();
        if (seg) yield JSON.parse(seg);
        pos += 1;
        // read the (small) trailer fully
        while (!ended) await pull();
        return finish(buf.slice(pos).trim());
      }
      else if (ch === '}' || ch === ']') { depth -= 1; pos += 1; }
      else if (ch === ',' && depth === 0) {
        const seg = buf.slice(elemStart, pos).trim();
        if (seg) yield JSON.parse(seg);
        pos += 1;
        buf = buf.slice(pos); pos = 0; elemStart = 0;
      }
      else pos += 1;
    }
    if (!(await pull())) throw new TruncatedStreamError('stream ended inside items array');
  }
}

function finish(trailer) {
  if (!trailer) throw new TruncatedStreamError('stream ended before terminal status');
  const obj = JSON.parse('{' + trailer.replace(/^,/, ''));
  if (!('complete' in obj)) throw new TruncatedStreamError('stream ended before terminal status');
  if (!obj.complete) throw new StreamError(obj.error != null ? obj.error : 'unknown stream error');
}

module.exports = { encodeCheckedArray, decodeCheckedArray, StreamError, TruncatedStreamError };
