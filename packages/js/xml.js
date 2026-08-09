'use strict';

// Streaming XML format for flatwire (Node), mirroring the Python reference.
//
// XML has no native types and no unambiguous list representation, so flatwire
// uses an explicit, typed, fully round-trippable convention:
//
//   42        -> <item type="int">42</item>
//   "hi"      -> <item type="str">hi</item>
//   true      -> <item type="bool">true</item>
//   null      -> <item type="null"/>
//   {"id":1}  -> <item type="object"><f k="id" type="int">1</f></item>
//   [1,2]     -> <item type="array"><e type="int">1</e><e type="int">2</e></item>
//
// encodeArray streams one <item> at a time. decodeArray scans the stream with a
// persistent cursor (like the JSON decoder), collecting each top-level <item>…
// </item> subtree and parsing it, so peak memory stays bounded by one element.

const { StringDecoder } = require('node:string_decoder');

function escapeText(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
function escapeAttr(s) {
  return escapeText(s).replace(/"/g, '&quot;');
}
function unescape(s) {
  return s
    .replace(/&quot;/g, '"')
    .replace(/&gt;/g, '>')
    .replace(/&lt;/g, '<')
    .replace(/&amp;/g, '&');
}

function typeOf(v) {
  if (v === null || v === undefined) return 'null';
  if (typeof v === 'boolean') return 'bool';
  if (typeof v === 'number') return Number.isSafeInteger(v) ? 'int' : 'float';
  if (typeof v === 'string') return 'str';
  if (Array.isArray(v)) return 'array';
  if (typeof v === 'object') return 'object';
  throw new TypeError(`flatwire xml: unsupported type ${typeof v}`);
}

function writeValue(v, tag, extraAttrs, parts) {
  const t = typeOf(v);
  const attrs = ` type="${t}"${extraAttrs}`;
  if (t === 'null') {
    parts.push(`<${tag}${attrs}/>`);
  } else if (t === 'object') {
    parts.push(`<${tag}${attrs}>`);
    for (const [k, val] of Object.entries(v)) writeValue(val, 'f', ` k="${escapeAttr(k)}"`, parts);
    parts.push(`</${tag}>`);
  } else if (t === 'array') {
    parts.push(`<${tag}${attrs}>`);
    for (const item of v) writeValue(item, 'e', '', parts);
    parts.push(`</${tag}>`);
  } else {
    const text = t === 'bool' ? (v ? 'true' : 'false') : String(v);
    parts.push(`<${tag}${attrs}>${escapeText(text)}</${tag}>`);
  }
}

// --- a tiny DOM parser for a single, already-buffered <item>…</item> string ---
// Our XML is self-generated and constrained, so a focused recursive parser is
// enough (and avoids a third-party dependency).

function parseElement(xml, cursor) {
  // cursor.i points at '<'. Returns the reconstructed value; advances cursor.
  // Expect: <tag attrs> ... </tag>  or  <tag attrs/>
  if (xml[cursor.i] !== '<') throw new Error('flatwire xml: expected <');
  const tagEnd = xml.indexOf('>', cursor.i);
  const openRaw = xml.slice(cursor.i + 1, tagEnd); // e.g. f k="id" type="int"  (maybe trailing /)
  const selfClose = openRaw.endsWith('/');
  const head = selfClose ? openRaw.slice(0, -1) : openRaw;
  const attrs = parseAttrs(head);
  const t = attrs.type;
  cursor.i = tagEnd + 1;

  if (t === 'null') {
    if (!selfClose) skipToClose(xml, cursor); // tolerate <x type="null"></x>
    return { value: null, attrs };
  }
  if (t === 'object') {
    const obj = {};
    while (xml[cursor.i] !== '<' || xml[cursor.i + 1] !== '/') {
      const child = parseElement(xml, cursor);
      obj[child.attrs.k] = child.value;
    }
    skipToClose(xml, cursor);
    return { value: obj, attrs };
  }
  if (t === 'array') {
    const arr = [];
    while (xml[cursor.i] !== '<' || xml[cursor.i + 1] !== '/') {
      const child = parseElement(xml, cursor);
      arr.push(child.value);
    }
    skipToClose(xml, cursor);
    return { value: arr, attrs };
  }
  // scalar: read text up to </tag>
  const close = xml.indexOf('<', cursor.i);
  const raw = unescape(xml.slice(cursor.i, close));
  cursor.i = close;
  skipToClose(xml, cursor);
  let value;
  if (t === 'int') value = parseInt(raw, 10);
  else if (t === 'float') value = parseFloat(raw);
  else if (t === 'bool') value = raw === 'true';
  else value = raw; // str
  return { value, attrs };
}

function skipToClose(xml, cursor) {
  // cursor at '</'; skip to after '>'
  const gt = xml.indexOf('>', cursor.i);
  cursor.i = gt + 1;
}

function parseAttrs(head) {
  const attrs = {};
  const re = /(\w+)="([^"]*)"/g;
  let m;
  while ((m = re.exec(head)) !== null) attrs[m[1]] = unescape(m[2]);
  return attrs;
}

async function encodeArray(items, writable, { root = 'items' } = {}) {
  const write = (chunk) =>
    new Promise((resolve, reject) => writable.write(chunk, (e) => (e ? reject(e) : resolve())));
  await write(Buffer.from(`<?xml version="1.0" encoding="UTF-8"?><${root}>`, 'utf8'));
  let count = 0;
  for await (const v of items) {
    const parts = [];
    writeValue(v, 'item', '', parts);
    await write(Buffer.from(parts.join(''), 'utf8'));
    count += 1;
  }
  await write(Buffer.from(`</${root}>`, 'utf8'));
  return count;
}

// Streaming decode: scan for top-level <item>…</item> spans (depth 1 relative to
// root) with a persistent cursor, parse each, and drop consumed bytes so the
// buffer never grows with the collection.
async function* decodeArray(readable, { item = 'item' } = {}) {
  let buf = '';
  const decoder = new StringDecoder('utf8');
  const openTag = `<${item} `;
  const openTagNoAttr = `<${item}>`;
  const openSelf = `<${item}`;
  const closeTag = `</${item}>`;

  for await (const chunk of readable) {
    buf += Buffer.isBuffer(chunk) ? decoder.write(chunk) : chunk;

    // Repeatedly extract complete <item>…</item> (or <item …/>) spans.
    // eslint-disable-next-line no-constant-condition
    while (true) {
      const start = indexOfItem(buf, openSelf);
      if (start === -1) break;
      // Determine if this item is self-closing or has a matching close tag.
      const span = extractItemSpan(buf, start, item);
      if (span === null) break; // incomplete; wait for more data
      const xml = buf.slice(span.start, span.end);
      const cursor = { i: 0 };
      yield parseElement(xml, cursor).value;
      buf = buf.slice(span.end);
    }
  }
}

// Find the next '<item' that begins an element (followed by space, '>' or '/').
function indexOfItem(buf, openSelf) {
  let from = 0;
  for (;;) {
    const idx = buf.indexOf(openSelf, from);
    if (idx === -1) return -1;
    const after = buf[idx + openSelf.length];
    if (after === ' ' || after === '>' || after === '/') return idx;
    from = idx + 1;
  }
}

// Given buf and the index of a top-level '<item', return {start,end} of the full
// element (accounting for nested <item>? no - items don't nest; but objects use
// <f>/<e>, not <item>, so a simple close-tag search at this level is safe).
function extractItemSpan(buf, start, item) {
  // self-closing: <item .../>
  const firstGt = buf.indexOf('>', start);
  if (firstGt === -1) return null;
  if (buf[firstGt - 1] === '/') return { start, end: firstGt + 1 };
  const close = buf.indexOf(`</${item}>`, firstGt);
  if (close === -1) return null;
  return { start, end: close + `</${item}>`.length };
}

module.exports = { encodeArray, decodeArray };
