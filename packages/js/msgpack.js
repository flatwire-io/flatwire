'use strict';

// Streaming MessagePack (binary) format for flatwire (Node), mirroring the Python
// reference. flatwire's binary wire is a STREAM OF CONCATENATED MessagePack
// values (not a length-prefixed array), so encoding an open-ended iterable needs
// no upfront count and the decoder reads one value at a time. Wire-compatible
// with the reference `msgpack`/`@msgpack/msgpack` libraries for the JSON data
// model (null/bool/int/float/str/bin/array/map). No ext types/timestamps.

// --- encoding: build a Buffer per element ----------------------------------

function encodeValue(v, chunks) {
  if (v === null || v === undefined) {
    chunks.push(Buffer.from([0xc0]));
  } else if (v === true) {
    chunks.push(Buffer.from([0xc3]));
  } else if (v === false) {
    chunks.push(Buffer.from([0xc2]));
  } else if (typeof v === 'number') {
    // Only a safe integer is encoded as a msgpack int; integer-valued numbers
    // beyond 2^53 (e.g. 1e300) are not 64-bit ints and must go out as floats.
    if (Number.isSafeInteger(v)) encodeInt(v, chunks);
    else { const b = Buffer.allocUnsafe(9); b[0] = 0xcb; b.writeDoubleBE(v, 1); chunks.push(b); }
  } else if (typeof v === 'bigint') {
    encodeBigInt(v, chunks);
  } else if (typeof v === 'string') {
    encodeStr(v, chunks);
  } else if (Buffer.isBuffer(v) || v instanceof Uint8Array) {
    encodeBin(Buffer.from(v), chunks);
  } else if (Array.isArray(v)) {
    encodeArrayHeader(v.length, chunks);
    for (const e of v) encodeValue(e, chunks);
  } else if (typeof v === 'object') {
    // Canonical: sort keys so the encoding is byte-identical regardless of
    // insertion order.
    const keys = Object.keys(v).sort();
    encodeMapHeader(keys.length, chunks);
    for (const k of keys) { encodeStr(k, chunks); encodeValue(v[k], chunks); }
  } else {
    throw new TypeError(`flatwire msgpack: unsupported type ${typeof v}`);
  }
}

function encodeInt(v, chunks) {
  // Canonical scheme (byte-identical across all flatwire languages):
  //   -32..127     -> fixint
  //   non-negative -> smallest UNSIGNED type
  //   negative     -> smallest SIGNED type
  if (v >= -32 && v <= 127) return chunks.push(Buffer.from([v & 0xff]));
  let b;
  if (v >= 0) {
    if (v <= 0xff) { b = Buffer.from([0xcc, v]); }
    else if (v <= 0xffff) { b = Buffer.allocUnsafe(3); b[0] = 0xcd; b.writeUInt16BE(v, 1); }
    else if (v <= 0xffffffff) { b = Buffer.allocUnsafe(5); b[0] = 0xce; b.writeUInt32BE(v, 1); }
    else { return encodeBigInt(BigInt(v), chunks); }
  } else {
    if (v >= -0x80) { b = Buffer.allocUnsafe(2); b[0] = 0xd0; b.writeInt8(v, 1); }
    else if (v >= -0x8000) { b = Buffer.allocUnsafe(3); b[0] = 0xd1; b.writeInt16BE(v, 1); }
    else if (v >= -0x80000000) { b = Buffer.allocUnsafe(5); b[0] = 0xd2; b.writeInt32BE(v, 1); }
    else { return encodeBigInt(BigInt(v), chunks); }
  }
  chunks.push(b);
}

function encodeBigInt(v, chunks) {
  const b = Buffer.allocUnsafe(9);
  if (v >= 0n) { b[0] = 0xcf; b.writeBigUInt64BE(v, 1); }
  else { b[0] = 0xd3; b.writeBigInt64BE(v, 1); }
  chunks.push(b);
}

function encodeStr(s, chunks) {
  const body = Buffer.from(s, 'utf8');
  const n = body.length;
  let head;
  if (n <= 31) head = Buffer.from([0xa0 | n]);
  else if (n <= 0xff) head = Buffer.from([0xd9, n]);
  else if (n <= 0xffff) { head = Buffer.allocUnsafe(3); head[0] = 0xda; head.writeUInt16BE(n, 1); }
  else { head = Buffer.allocUnsafe(5); head[0] = 0xdb; head.writeUInt32BE(n, 1); }
  chunks.push(head, body);
}

function encodeBin(body, chunks) {
  const n = body.length;
  let head;
  if (n <= 0xff) head = Buffer.from([0xc4, n]);
  else if (n <= 0xffff) { head = Buffer.allocUnsafe(3); head[0] = 0xc5; head.writeUInt16BE(n, 1); }
  else { head = Buffer.allocUnsafe(5); head[0] = 0xc6; head.writeUInt32BE(n, 1); }
  chunks.push(head, body);
}

function encodeArrayHeader(n, chunks) {
  if (n <= 15) chunks.push(Buffer.from([0x90 | n]));
  else if (n <= 0xffff) { const b = Buffer.allocUnsafe(3); b[0] = 0xdc; b.writeUInt16BE(n, 1); chunks.push(b); }
  else { const b = Buffer.allocUnsafe(5); b[0] = 0xdd; b.writeUInt32BE(n, 1); chunks.push(b); }
}

function encodeMapHeader(n, chunks) {
  if (n <= 15) chunks.push(Buffer.from([0x80 | n]));
  else if (n <= 0xffff) { const b = Buffer.allocUnsafe(3); b[0] = 0xde; b.writeUInt16BE(n, 1); chunks.push(b); }
  else { const b = Buffer.allocUnsafe(5); b[0] = 0xdf; b.writeUInt32BE(n, 1); chunks.push(b); }
}

async function encodeArray(items, writable) {
  const write = (chunk) =>
    new Promise((resolve, reject) => writable.write(chunk, (e) => (e ? reject(e) : resolve())));
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
    // Compact consumed prefix so memory stays bounded.
    if (this.pos > 0) { this.buf = this.buf.subarray(this.pos); this.pos = 0; }
    this.buf = this.buf.length ? Buffer.concat([this.buf, chunk]) : chunk;
    return true;
  }
  async ensure(n) {
    while (this.buf.length - this.pos < n) {
      if (!(await this._pull())) throw new Error('flatwire msgpack: truncated value');
    }
  }
  async atEnd() {
    while (this.pos >= this.buf.length) {
      if (!(await this._pull())) return true; // stream exhausted
      // a pulled chunk may be empty (e.g. Readable.from(emptyBuffer)); loop.
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

  async readValue() {
    const c = await this.u8();
    if (c <= 0x7f) return c;
    if (c >= 0xe0) return c - 0x100;
    if (c >= 0x80 && c <= 0x8f) return this._map(c & 0x0f);
    if (c >= 0x90 && c <= 0x9f) return this._arr(c & 0x0f);
    if (c >= 0xa0 && c <= 0xbf) return (await this.take(c & 0x1f)).toString('utf8');
    switch (c) {
      case 0xc0: return null;
      case 0xc2: return false;
      case 0xc3: return true;
      case 0xc4: return Buffer.from(await this.take(await this.u8()));
      case 0xc5: return Buffer.from(await this.take((await this.take(2)).readUInt16BE(0)));
      case 0xc6: return Buffer.from(await this.take((await this.take(4)).readUInt32BE(0)));
      case 0xca: return (await this.take(4)).readFloatBE(0);
      case 0xcb: return (await this.take(8)).readDoubleBE(0);
      case 0xcc: return await this.u8();
      case 0xcd: return (await this.take(2)).readUInt16BE(0);
      case 0xce: return (await this.take(4)).readUInt32BE(0);
      case 0xcf: return numberOrBig((await this.take(8)).readBigUInt64BE(0));
      case 0xd0: return (await this.take(1)).readInt8(0);
      case 0xd1: return (await this.take(2)).readInt16BE(0);
      case 0xd2: return (await this.take(4)).readInt32BE(0);
      case 0xd3: return numberOrBig((await this.take(8)).readBigInt64BE(0));
      case 0xd9: return (await this.take(await this.u8())).toString('utf8');
      case 0xda: return (await this.take((await this.take(2)).readUInt16BE(0))).toString('utf8');
      case 0xdb: return (await this.take((await this.take(4)).readUInt32BE(0))).toString('utf8');
      case 0xdc: return this._arr((await this.take(2)).readUInt16BE(0));
      case 0xdd: return this._arr((await this.take(4)).readUInt32BE(0));
      case 0xde: return this._map((await this.take(2)).readUInt16BE(0));
      case 0xdf: return this._map((await this.take(4)).readUInt32BE(0));
      default: throw new Error(`flatwire msgpack: unknown prefix 0x${c.toString(16)}`);
    }
  }
  async _arr(n) { const a = new Array(n); for (let i = 0; i < n; i++) a[i] = await this.readValue(); return a; }
  async _map(n) { const o = {}; for (let i = 0; i < n; i++) { const k = await this.readValue(); o[k] = await this.readValue(); } return o; }
}

function numberOrBig(big) {
  return big >= BigInt(Number.MIN_SAFE_INTEGER) && big <= BigInt(Number.MAX_SAFE_INTEGER)
    ? Number(big) : big;
}

async function* decodeArray(readable) {
  const r = new Reader(readable);
  while (!(await r.atEnd())) {
    yield await r.readValue();
  }
}

module.exports = { encodeArray, decodeArray };
