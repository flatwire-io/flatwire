'use strict';

// flatwire playground codec — browser-native encode/decode + a byte-level
// MessagePack inspector. This mirrors the canonical flatwire wire (same integer
// scheme, sorted map keys, IEEE floats) so what you see here is what flatwire
// emits in every language. Zero dependencies; runs entirely in the browser.

const flatwirePlayground = (() => {
  // ---- MessagePack encode (canonical, matches packages/*/msgpack) ----------
  function encodeValue(v, out) {
    if (v === null) { out.push(0xc0); return; }
    if (v === true) { out.push(0xc3); return; }
    if (v === false) { out.push(0xc2); return; }
    if (typeof v === 'number') {
      if (Number.isSafeInteger(v)) return encodeInt(v, out);
      const b = new DataView(new ArrayBuffer(8)); b.setFloat64(0, v, false);
      out.push(0xcb); for (let i = 0; i < 8; i++) out.push(b.getUint8(i)); return;
    }
    if (typeof v === 'string') return encodeStr(v, out);
    if (Array.isArray(v)) {
      writeLen(out, v.length, 0x90, 0xdc, 0xdd);
      for (const e of v) encodeValue(e, out);
      return;
    }
    if (typeof v === 'object') {
      const keys = Object.keys(v).sort();
      writeLen(out, keys.length, 0x80, 0xde, 0xdf);
      for (const k of keys) { encodeStr(k, out); encodeValue(v[k], out); }
      return;
    }
    throw new Error('unsupported type ' + typeof v);
  }
  function encodeInt(v, out) {
    if (v >= -32 && v <= 127) { out.push(v & 0xff); return; }
    const dv = new DataView(new ArrayBuffer(8));
    if (v >= 0) {
      if (v <= 0xff) { out.push(0xcc, v); }
      else if (v <= 0xffff) { dv.setUint16(0, v, false); out.push(0xcd, dv.getUint8(0), dv.getUint8(1)); }
      else if (v <= 0xffffffff) { dv.setUint32(0, v, false); out.push(0xce); for (let i = 0; i < 4; i++) out.push(dv.getUint8(i)); }
      else { dv.setBigUint64(0, BigInt(v), false); out.push(0xcf); for (let i = 0; i < 8; i++) out.push(dv.getUint8(i)); }
    } else {
      if (v >= -0x80) { out.push(0xd0, v & 0xff); }
      else if (v >= -0x8000) { dv.setInt16(0, v, false); out.push(0xd1, dv.getUint8(0), dv.getUint8(1)); }
      else if (v >= -0x80000000) { dv.setInt32(0, v, false); out.push(0xd2); for (let i = 0; i < 4; i++) out.push(dv.getUint8(i)); }
      else { dv.setBigInt64(0, BigInt(v), false); out.push(0xd3); for (let i = 0; i < 8; i++) out.push(dv.getUint8(i)); }
    }
  }
  function encodeStr(s, out) {
    const body = new TextEncoder().encode(s);
    const n = body.length;
    if (n <= 31) out.push(0xa0 | n);
    else if (n <= 0xff) out.push(0xd9, n);
    else if (n <= 0xffff) { out.push(0xda, (n >> 8) & 0xff, n & 0xff); }
    else { out.push(0xdb, (n >>> 24) & 0xff, (n >> 16) & 0xff, (n >> 8) & 0xff, n & 0xff); }
    for (const b of body) out.push(b);
  }
  function writeLen(out, n, fix, b16, b32) {
    if (n <= 15) out.push(fix | n);
    else if (n <= 0xffff) out.push(b16, (n >> 8) & 0xff, n & 0xff);
    else out.push(b32, (n >>> 24) & 0xff, (n >> 16) & 0xff, (n >> 8) & 0xff, n & 0xff);
  }

  function encodeArrayMsgpack(items) {
    const out = [];
    for (const it of items) encodeValue(it, out);
    return new Uint8Array(out);
  }

  // ---- JSON (matches flatwire encode_array: compact single array) ----------
  function encodeArrayJson(items) {
    const parts = items.map((it) => JSON.stringify(it));
    return new TextEncoder().encode('[' + parts.join(',') + ']');
  }
  function decodeArrayJson(bytes) {
    return JSON.parse(new TextDecoder().decode(bytes));
  }

  // ---- XML (typed, matches flatwire xml.js convention) ---------------------
  function xmlType(v) {
    if (v === null) return 'null';
    if (typeof v === 'boolean') return 'bool';
    if (typeof v === 'number') return Number.isSafeInteger(v) ? 'int' : 'float';
    if (typeof v === 'string') return 'str';
    if (Array.isArray(v)) return 'array';
    if (typeof v === 'object') return 'object';
    throw new Error('unsupported type ' + typeof v);
  }
  function xmlEsc(s) { return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
  function xmlAttrEsc(s) { return xmlEsc(s).replace(/"/g, '&quot;'); }
  function xmlWriteValue(v, tag, keyAttr, parts) {
    const t = xmlType(v);
    const attrs = ` type="${t}"${keyAttr}`;
    if (t === 'null') { parts.push(`<${tag}${attrs}/>`); }
    else if (t === 'object') {
      parts.push(`<${tag}${attrs}>`);
      for (const [k, val] of Object.entries(v)) xmlWriteValue(val, 'f', ` k="${xmlAttrEsc(k)}"`, parts);
      parts.push(`</${tag}>`);
    } else if (t === 'array') {
      parts.push(`<${tag}${attrs}>`);
      for (const e of v) xmlWriteValue(e, 'e', '', parts);
      parts.push(`</${tag}>`);
    } else {
      const text = t === 'bool' ? (v ? 'true' : 'false') : String(v);
      parts.push(`<${tag}${attrs}>${xmlEsc(text)}</${tag}>`);
    }
  }
  function encodeArrayXml(items, root = 'items') {
    const parts = [`<?xml version="1.0" encoding="UTF-8"?><${root}>`];
    for (const it of items) xmlWriteValue(it, 'item', '', parts);
    parts.push(`</${root}>`);
    return new TextEncoder().encode(parts.join(''));
  }
  function decodeArrayXml(bytes, itemTag = 'item') {
    const doc = new DOMParser().parseFromString(new TextDecoder().decode(bytes), 'application/xml');
    const err = doc.querySelector('parsererror');
    if (err) throw new Error('invalid XML: ' + err.textContent.trim());
    const root = doc.documentElement;
    const out = [];
    for (const el of root.children) if (el.tagName === itemTag) out.push(xmlParseEl(el));
    return out;
  }
  function xmlParseEl(el) {
    const t = el.getAttribute('type');
    if (t === 'null') return null;
    if (t === 'bool') return (el.textContent || '').trim() === 'true';
    if (t === 'int') return parseInt(el.textContent, 10);
    if (t === 'float') return parseFloat(el.textContent);
    if (t === 'str') return el.textContent || '';
    if (t === 'object') { const o = {}; for (const c of el.children) o[c.getAttribute('k')] = xmlParseEl(c); return o; }
    if (t === 'array') { const a = []; for (const c of el.children) a.push(xmlParseEl(c)); return a; }
    throw new Error('unknown xml type ' + t);
  }

  // ---- compute everything for a set of items -------------------------------
  function canonical(v) {
    // Stable, order-insensitive, bigint-safe stringify for round-trip checks
    // (canonical msgpack sorts map keys, so comparison must ignore key order).
    if (typeof v === 'bigint') return v.toString();
    if (v === null || typeof v !== 'object') return JSON.stringify(v);
    if (Array.isArray(v)) return '[' + v.map(canonical).join(',') + ']';
    return '{' + Object.keys(v).sort().map((k) => JSON.stringify(k) + ':' + canonical(v[k])).join(',') + '}';
  }
  function computeAll(items) {
    const j = encodeArrayJson(items);
    const x = encodeArrayXml(items);
    const m = encodeArrayMsgpack(items);
    const want = canonical(items);
    const rt = (dec) => { try { return canonical(dec) === want; } catch { return false; } };
    return {
      json: { bytes: j, size: j.length, roundtrip: rt(decodeArrayJson(j)) },
      xml: { bytes: x, size: x.length, roundtrip: rt(decodeArrayXml(x)) },
      msgpack: { bytes: m, size: m.length, roundtrip: rt(inspectMsgpack(m).values) },
    };
  }

  // ---- MessagePack decode with byte annotations ----------------------------
  // Returns { values: [...], tokens: [{start,end,type,label,depth}] }
  function inspectMsgpack(bytes) {
    let pos = 0;
    const tokens = [];
    const values = [];
    const dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);

    function u8() { return bytes[pos++]; }
    function slice(n) { const s = bytes.subarray(pos, pos + n); pos += n; return s; }

    function readValue(depth) {
      const start = pos;
      const c = u8();
      let type, label, value;
      if (c <= 0x7f) { type = 'int'; value = c; label = `positive fixint ${c}`; }
      else if (c >= 0xe0) { type = 'int'; value = c - 0x100; label = `negative fixint ${value}`; }
      else if (c >= 0x80 && c <= 0x8f) { return readMap(c & 0x0f, start, depth, 'fixmap'); }
      else if (c >= 0x90 && c <= 0x9f) { return readArr(c & 0x0f, start, depth, 'fixarray'); }
      else if (c >= 0xa0 && c <= 0xbf) { const n = c & 0x1f; value = new TextDecoder().decode(slice(n)); type = 'str'; label = `fixstr(${n}) "${value}"`; }
      else {
        switch (c) {
          case 0xc0: type = 'null'; value = null; label = 'nil'; break;
          case 0xc2: type = 'bool'; value = false; label = 'false'; break;
          case 0xc3: type = 'bool'; value = true; label = 'true'; break;
          case 0xca: value = dv.getFloat32(pos, false); pos += 4; type = 'float'; label = `float32 ${value}`; break;
          case 0xcb: value = dv.getFloat64(pos, false); pos += 8; type = 'float'; label = `float64 ${value}`; break;
          case 0xcc: value = u8(); type = 'int'; label = `uint8 ${value}`; break;
          case 0xcd: value = dv.getUint16(pos, false); pos += 2; type = 'int'; label = `uint16 ${value}`; break;
          case 0xce: value = dv.getUint32(pos, false); pos += 4; type = 'int'; label = `uint32 ${value}`; break;
          case 0xcf: value = dv.getBigUint64(pos, false); pos += 8; type = 'int'; label = `uint64 ${value}`; break;
          case 0xd0: value = dv.getInt8(pos); pos += 1; type = 'int'; label = `int8 ${value}`; break;
          case 0xd1: value = dv.getInt16(pos, false); pos += 2; type = 'int'; label = `int16 ${value}`; break;
          case 0xd2: value = dv.getInt32(pos, false); pos += 4; type = 'int'; label = `int32 ${value}`; break;
          case 0xd3: value = dv.getBigInt64(pos, false); pos += 8; type = 'int'; label = `int64 ${value}`; break;
          case 0xd9: { const n = u8(); value = new TextDecoder().decode(slice(n)); type = 'str'; label = `str8(${n}) "${value}"`; break; }
          case 0xda: { const n = dv.getUint16(pos, false); pos += 2; value = new TextDecoder().decode(slice(n)); type = 'str'; label = `str16(${n}) "${value}"`; break; }
          case 0xdb: { const n = dv.getUint32(pos, false); pos += 4; value = new TextDecoder().decode(slice(n)); type = 'str'; label = `str32(${n}) "${value}"`; break; }
          case 0xdc: { const n = dv.getUint16(pos, false); pos += 2; return readArr(n, start, depth, 'array16'); }
          case 0xdd: { const n = dv.getUint32(pos, false); pos += 4; return readArr(n, start, depth, 'array32'); }
          case 0xde: { const n = dv.getUint16(pos, false); pos += 2; return readMap(n, start, depth, 'map16'); }
          case 0xdf: { const n = dv.getUint32(pos, false); pos += 4; return readMap(n, start, depth, 'map32'); }
          default: throw new Error(`unknown prefix 0x${c.toString(16)} at byte ${start}`);
        }
      }
      tokens.push({ start, end: pos, type, label, depth });
      return value;
    }

    function readArr(n, start, depth, kind) {
      tokens.push({ start, end: pos, type: 'array', label: `${kind}[${n}]`, depth });
      const arr = [];
      for (let i = 0; i < n; i++) arr.push(readValue(depth + 1));
      return arr;
    }
    function readMap(n, start, depth, kind) {
      tokens.push({ start, end: pos, type: 'map', label: `${kind}{${n}}`, depth });
      const obj = {};
      for (let i = 0; i < n; i++) { const k = readValue(depth + 1); obj[k] = readValue(depth + 1); }
      return obj;
    }

    while (pos < bytes.length) values.push(readValue(0));
    return { values, tokens };
  }

  // ---- helpers -------------------------------------------------------------
  function hexToBytes(hex) {
    const clean = hex.replace(/0x/gi, '').replace(/[\s,]/g, '');
    if (clean.length % 2) throw new Error('hex has an odd number of digits');
    const out = new Uint8Array(clean.length / 2);
    for (let i = 0; i < out.length; i++) out[i] = parseInt(clean.substr(i * 2, 2), 16);
    return out;
  }
  function base64ToBytes(b64) {
    const bin = atob(b64.trim());
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }
  function bytesToHex(bytes) {
    return Array.from(bytes).map((b) => b.toString(16).padStart(2, '0')).join(' ');
  }

  return {
    encodeArrayJson, decodeArrayJson,
    encodeArrayXml, decodeArrayXml,
    encodeArrayMsgpack, inspectMsgpack,
    computeAll, hexToBytes, base64ToBytes, bytesToHex,
  };
})();

if (typeof module !== 'undefined') module.exports = flatwirePlayground;
