'use strict';

// Streaming CBOR (RFC 8949 binary) format for flatwire (Node), mirroring the
// Python reference. flatwire's CBOR wire is a STREAM OF CONCATENATED CBOR data
// items (not a length-prefixed array), so encoding an open-ended iterable needs
// no upfront count and the decoder reads one item at a time. The encoding is
// deterministic (shortest heads, sorted map keys by UTF-8 bytes, 64-bit floats)
// so output is byte-identical across all six flatwire languages. Covers the JSON
// data model (null/bool/int/float/str/bytes/array/map); no tags.

// --- encoding: build a Buffer per element ----------------------------------

function head(major, n, chunks) {
  const mt = major << 5;
  if (typeof n === 'bigint') return headBig(major, n, chunks);
  if (n < 24) { chunks.push(Buffer.from([mt | n])); }
  else if (n <= 0xff) { chunks.push(Buffer.from([mt | 24, n])); }
  else if (n <= 0xffff) { const b = Buffer.allocUnsafe(3); b[0] = mt | 25; b.writeUInt16BE(n, 1); chunks.push(b); }
  else if (n <= 0xffffffff) { const b = Buffer.allocUnsafe(5); b[0] = mt | 26; b.writeUInt32BE(n, 1); chunks.push(b); }
  else { const b = Buffer.allocUnsafe(9); b[0] = mt | 27; b.writeBigUInt64BE(BigInt(n), 1); chunks.push(b); }
}

function headBig(major, n, chunks) {
  const mt = major << 5;
  if (n <= 0xffffffffn) return head(major, Number(n), chunks);
  const b = Buffer.allocUnsafe(9); b[0] = mt | 27; b.writeBigUInt64BE(n, 1); chunks.push(b);
}

function encodeValue(v, chunks) {
  if (v === null || v === undefined) {
    chunks.push(Buffer.from([0xf6]));
  } else if (v === true) {
    chunks.push(Buffer.from([0xf5]));
  } else if (v === false) {
    chunks.push(Buffer.from([0xf4]));
  } else if (typeof v === 'number') {
    // Integer-valued numbers beyond 2^53 are not 64-bit ints; emit as float64.
    if (Number.isSafeInteger(v)) {
      if (v >= 0) head(0, v, chunks);
      else head(1, -1 - v, chunks);
    } else {
      const b = Buffer.allocUnsafe(9); b[0] = 0xfb; b.writeDoubleBE(v, 1); chunks.push(b);
    }
  } else if (typeof v === 'bigint') {
    if (v >= 0n) head(0, v, chunks);
    else head(1, -1n - v, chunks);
  } else if (typeof v === 'string') {
    const body = Buffer.from(v, 'utf8');
    head(3, body.length, chunks);
    chunks.push(body);
  } else if (Buffer.isBuffer(v) || v instanceof Uint8Array) {
    const body = Buffer.from(v);
    head(2, body.length, chunks);
    chunks.push(body);
  } else if (Array.isArray(v)) {
    head(4, v.length, chunks);
    for (const e of v) encodeValue(e, chunks);
  } else if (typeof v === 'object') {
    // Deterministic: sort keys by their UTF-8 byte sequence.
    const keys = Object.keys(v).sort(compareUtf8);
    head(5, keys.length, chunks);
    for (const k of keys) { const kb = Buffer.from(k, 'utf8'); head(3, kb.length, chunks); chunks.push(kb); encodeValue(v[k], chunks); }
  } else {
    throw new TypeError(`flatwire cbor: unsupported type ${typeof v}`);
  }
}

function compareUtf8(a, b) {
  return Buffer.compare(Buffer.from(a, 'utf8'), Buffer.from(b, 'utf8'));
}

async function encodeArray(items, writable) {
  const write = (chunk) =>
    new Promise((resolve, reject) => {
      const onError = (e) => { writable.removeListener('error', onError); reject(e); };
      writable.once('error', onError);
      const ok = writable.write(chunk);
      if (ok) { writable.removeListener('error', onError); resolve(); }
      else writable.once('drain', () => { writable.removeListener('error', onError); resolve(); });
    });
  let count = 0;
  for await (const item of items) {
    const chunks = [];
    encodeValue(item, chunks);
    await write(Buffer.concat(chunks));
    count += 1;
  }
  return count;
}

// --- decoding: buffered reader over the stream -----------------------------

class Reader {
  constructor(readable) {
    this.iter = readable[Symbol.asyncIterator]();
    this.buf = Buffer.alloc(0);
    this.pos = 0;
    this.done = false;
  }
  async _pull() {
    if (this.done) return false;
    const { value, done } = await this.iter.next();
    if (done) { this.done = true; return false; }
    const chunk = Buffer.isBuffer(value) ? value : Buffer.from(value);
    if (this.pos > 0) { this.buf = this.buf.subarray(this.pos); this.pos = 0; }
    this.buf = this.buf.length ? Buffer.concat([this.buf, chunk]) : chunk;
    return true;
  }
  async ensure(n) {
    while (this.buf.length - this.pos < n) {
      if (!(await this._pull())) throw new Error('flatwire cbor: truncated value');
    }
  }
  async atEnd() {
    while (this.pos >= this.buf.length) {
      if (!(await this._pull())) return true;
    }
    return false;
  }
  async take(n) {
    await this.ensure(n);
    const b = this.buf.subarray(this.pos, this.pos + n);
    this.pos += n;
    return b;
  }
  async u8() { return (await this.take(1))[0]; }

  async argument(ai) {
    if (ai < 24) return ai;
    if (ai === 24) return this.u8();
    if (ai === 25) return (await this.take(2)).readUInt16BE(0);
    if (ai === 26) return (await this.take(4)).readUInt32BE(0);
    if (ai === 27) return numberOrBig((await this.take(8)).readBigUInt64BE(0));
    throw new Error(`flatwire cbor: unsupported additional info ${ai}`);
  }

  async readValue() {
    const ib = await this.u8();
    const major = ib >> 5;
    const ai = ib & 0x1f;
    switch (major) {
      case 0: return this.argument(ai);
      case 1: { const a = await this.argument(ai); return typeof a === 'bigint' ? -1n - a : -1 - a; }
      case 2: return Buffer.from(await this.take(Number(await this.argument(ai))));
      case 3: return (await this.take(Number(await this.argument(ai)))).toString('utf8');
      case 4: { const n = Number(await this.argument(ai)); const a = new Array(n); for (let i = 0; i < n; i++) a[i] = await this.readValue(); return a; }
      case 5: { const n = Number(await this.argument(ai)); const o = {}; for (let i = 0; i < n; i++) { const k = await this.readValue(); o[k] = await this.readValue(); } return o; }
      case 7:
        if (ai === 20) return false;
        if (ai === 21) return true;
        if (ai === 22) return null;
        if (ai === 23) return null; // undefined -> null
        if (ai === 25) return decodeFloat16(await this.take(2));
        if (ai === 26) return (await this.take(4)).readFloatBE(0);
        if (ai === 27) return (await this.take(8)).readDoubleBE(0);
        throw new Error(`flatwire cbor: unsupported simple value ${ai}`);
      default:
        throw new Error(`flatwire cbor: unsupported major type ${major}`);
    }
  }
}

function numberOrBig(big) {
  return big >= BigInt(Number.MIN_SAFE_INTEGER) && big <= BigInt(Number.MAX_SAFE_INTEGER)
    ? Number(big) : big;
}

function decodeFloat16(b) {
  const h = b.readUInt16BE(0);
  const sign = (h >> 15) & 0x1;
  const exp = (h >> 10) & 0x1f;
  const frac = h & 0x3ff;
  let val;
  if (exp === 0) val = (frac / 1024) * Math.pow(2, -14);
  else if (exp === 0x1f) val = frac === 0 ? Infinity : NaN;
  else val = (1 + frac / 1024) * Math.pow(2, exp - 15);
  return sign ? -val : val;
}

async function* decodeArray(readable) {
  const r = new Reader(readable);
  while (!(await r.atEnd())) {
    yield await r.readValue();
  }
}

module.exports = { encodeArray, decodeArray };
