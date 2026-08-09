//! Streaming XML format for flatwire, mirroring the JSON path and the Python/JS
//! reference. XML has no native types, so flatwire uses an explicit, typed,
//! fully round-trippable convention (see docs/FORMATS.md):
//!
//! ```text
//! 42        -> <item type="int">42</item>
//! "hi"      -> <item type="str">hi</item>
//! true      -> <item type="bool">true</item>
//! null      -> <item type="null"/>
//! {"id":1}  -> <item type="object"><f k="id" type="int">1</f></item>
//! [1,2]     -> <item type="array"><e type="int">1</e><e type="int">2</e></item>
//! ```
//!
//! Values are `serde_json::Value`, so the XML path is type-uniform with the JSON
//! path. Encoding writes one `<item>` at a time; decoding scans for top-level
//! `<item>...</item>` spans with a persistent cursor and parses each, so peak
//! memory stays bounded by the largest element. Tag markers are ASCII, and a
//! UTF-8 multibyte sequence never contains an ASCII `<`/`>`/`/` byte, so
//! byte-level boundary scanning is safe.

use std::io::{self, Read, Write};

use serde_json::Value;

fn escape_text(s: &str) -> String {
    s.replace('&', "&amp;").replace('<', "&lt;").replace('>', "&gt;")
}
fn escape_attr(s: &str) -> String {
    escape_text(s).replace('"', "&quot;")
}
fn unescape(s: &str) -> String {
    s.replace("&quot;", "\"")
        .replace("&gt;", ">")
        .replace("&lt;", "<")
        .replace("&amp;", "&")
}

fn type_of(v: &Value) -> &'static str {
    match v {
        Value::Null => "null",
        Value::Bool(_) => "bool",
        Value::Number(n) => {
            if n.is_i64() || n.is_u64() {
                "int"
            } else {
                "float"
            }
        }
        Value::String(_) => "str",
        Value::Array(_) => "array",
        Value::Object(_) => "object",
    }
}

fn write_value<W: Write>(w: &mut W, tag: &str, key: Option<&str>, v: &Value) -> io::Result<()> {
    let t = type_of(v);
    let key_attr = match key {
        Some(k) => format!(" k=\"{}\"", escape_attr(k)),
        None => String::new(),
    };
    match v {
        Value::Null => write!(w, "<{tag}{key_attr} type=\"null\"/>"),
        Value::Object(map) => {
            write!(w, "<{tag}{key_attr} type=\"object\">")?;
            for (k, val) in map {
                write_value(w, "f", Some(k), val)?;
            }
            write!(w, "</{tag}>")
        }
        Value::Array(arr) => {
            write!(w, "<{tag}{key_attr} type=\"array\">")?;
            for e in arr {
                write_value(w, "e", None, e)?;
            }
            write!(w, "</{tag}>")
        }
        Value::Bool(b) => write!(
            w,
            "<{tag}{key_attr} type=\"bool\">{}</{tag}>",
            if *b { "true" } else { "false" }
        ),
        Value::Number(n) => write!(w, "<{tag}{key_attr} type=\"{t}\">{n}</{tag}>"),
        Value::String(s) => write!(
            w,
            "<{tag}{key_attr} type=\"str\">{}</{tag}>",
            escape_text(s)
        ),
    }
}

/// Stream a collection as `<root>` containing one `<item>` per element.
pub fn encode_array<'a, I, W>(items: I, writer: &mut W, root: &str) -> io::Result<usize>
where
    I: IntoIterator<Item = &'a Value>,
    W: Write,
{
    write!(writer, "<?xml version=\"1.0\" encoding=\"UTF-8\"?><{root}>")?;
    let mut count = 0usize;
    for v in items {
        write_value(writer, "item", None, v)?;
        count += 1;
    }
    write!(writer, "</{root}>")?;
    Ok(count)
}

// --- streaming decode -------------------------------------------------------

/// A lazy iterator over the elements of a streamed XML collection.
pub struct XmlArrayIter<R: Read> {
    reader: R,
    buf: Vec<u8>,
    finished: bool,
    open: Vec<u8>,  // b"<item"
    close: Vec<u8>, // b"</item>"
}

/// Stream a top-level XML collection, yielding one element at a time.
pub fn decode_array<R: Read>(reader: R, item: &str) -> XmlArrayIter<R> {
    XmlArrayIter {
        reader,
        buf: Vec::new(),
        finished: false,
        open: format!("<{item}").into_bytes(),
        close: format!("</{item}>").into_bytes(),
    }
}

impl<R: Read> Iterator for XmlArrayIter<R> {
    type Item = io::Result<Value>;

    fn next(&mut self) -> Option<Self::Item> {
        if self.finished {
            return None;
        }
        loop {
            // Try to extract a complete <item ...>...</item> or <item .../> span.
            if let Some(start) = find_open(&self.buf, &self.open) {
                if let Some(end) = find_item_end(&self.buf, start, &self.close) {
                    let bytes = self.buf[start..end].to_vec();
                    // Drop everything up to end so the buffer never grows with the array.
                    self.buf.drain(0..end);
                    let text = match std::str::from_utf8(&bytes) {
                        Ok(s) => s,
                        Err(e) => {
                            self.finished = true;
                            return Some(Err(io::Error::new(io::ErrorKind::InvalidData, e)));
                        }
                    };
                    let mut cur = Cursor { s: text.as_bytes(), i: 0 };
                    return Some(parse_element(text, &mut cur).map(|(v, _)| v));
                }
            }
            // Need more data.
            let mut tmp = [0u8; 65536];
            match self.reader.read(&mut tmp) {
                Ok(0) => {
                    self.finished = true;
                    return None; // clean end (root closed)
                }
                Ok(k) => self.buf.extend_from_slice(&tmp[..k]),
                Err(e) => {
                    self.finished = true;
                    return Some(Err(e));
                }
            }
        }
    }
}

fn find_open(buf: &[u8], open: &[u8]) -> Option<usize> {
    let mut from = 0;
    while let Some(rel) = find_sub(&buf[from..], open) {
        let idx = from + rel;
        let after = buf.get(idx + open.len()).copied();
        if matches!(after, Some(b' ') | Some(b'>') | Some(b'/')) {
            return Some(idx);
        }
        from = idx + 1;
    }
    None
}

// Given the index of a top-level "<item", return the exclusive end of the full
// element. Items don't nest (objects use <f>/<e>), so a simple close search is
// safe.
fn find_item_end(buf: &[u8], start: usize, close: &[u8]) -> Option<usize> {
    let gt = find_sub(&buf[start..], b">").map(|r| start + r)?;
    if gt > 0 && buf[gt - 1] == b'/' {
        return Some(gt + 1); // self-closing <item .../>
    }
    let c = find_sub(&buf[gt..], close).map(|r| gt + r)?;
    Some(c + close.len())
}

fn find_sub(haystack: &[u8], needle: &[u8]) -> Option<usize> {
    if needle.is_empty() || haystack.len() < needle.len() {
        return None;
    }
    haystack
        .windows(needle.len())
        .position(|w| w == needle)
}

struct Cursor<'a> {
    s: &'a [u8],
    i: usize,
}

fn parse_element<'a>(full: &'a str, cur: &mut Cursor<'a>) -> io::Result<(Value, Option<String>)> {
    let bytes = cur.s;
    if bytes.get(cur.i) != Some(&b'<') {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "expected <"));
    }
    let tag_end = find_from(bytes, cur.i, b'>')
        .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidData, "unterminated tag"))?;
    let head = &full[cur.i + 1..tag_end];
    let self_close = head.ends_with('/');
    let head = if self_close { &head[..head.len() - 1] } else { head };
    let (ty, key) = parse_attrs(head);
    cur.i = tag_end + 1;

    let value = match ty.as_str() {
        "null" => {
            if !self_close {
                skip_to_close(bytes, cur);
            }
            Value::Null
        }
        "object" => {
            let mut map = serde_json::Map::new();
            if !self_close {
                while !(bytes.get(cur.i) == Some(&b'<') && bytes.get(cur.i + 1) == Some(&b'/')) {
                    let (v, k) = parse_element(full, cur)?;
                    map.insert(k.unwrap_or_default(), v);
                }
                skip_to_close(bytes, cur);
            }
            Value::Object(map)
        }
        "array" => {
            let mut arr = Vec::new();
            if !self_close {
                while !(bytes.get(cur.i) == Some(&b'<') && bytes.get(cur.i + 1) == Some(&b'/')) {
                    let (v, _) = parse_element(full, cur)?;
                    arr.push(v);
                }
                skip_to_close(bytes, cur);
            }
            Value::Array(arr)
        }
        _ => {
            // scalar
            if self_close {
                scalar_value(&ty, "")
            } else {
                let close = find_from(bytes, cur.i, b'<')
                    .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidData, "unterminated text"))?;
                let raw = unescape(&full[cur.i..close]);
                cur.i = close;
                skip_to_close(bytes, cur);
                scalar_value(&ty, &raw)
            }
        }
    };
    Ok((value, key))
}

fn scalar_value(ty: &str, raw: &str) -> Value {
    match ty {
        "int" => raw
            .parse::<i64>()
            .map(Value::from)
            .unwrap_or(Value::Null),
        "float" => raw
            .parse::<f64>()
            .ok()
            .and_then(serde_json::Number::from_f64)
            .map(Value::Number)
            .unwrap_or(Value::Null),
        "bool" => Value::Bool(raw == "true"),
        _ => Value::String(raw.to_string()),
    }
}

fn skip_to_close(bytes: &[u8], cur: &mut Cursor) {
    if let Some(gt) = find_from(bytes, cur.i, b'>') {
        cur.i = gt + 1;
    }
}

fn find_from(bytes: &[u8], from: usize, target: u8) -> Option<usize> {
    bytes[from..].iter().position(|&b| b == target).map(|r| from + r)
}

fn parse_attrs(head: &str) -> (String, Option<String>) {
    let mut ty = String::from("str");
    let mut key = None;
    let bytes = head.as_bytes();
    let mut i = 0;
    while i < bytes.len() {
        if let Some(eq) = find_from(bytes, i, b'=') {
            // The attribute name is the whitespace-delimited token ending at '='.
            let name_start = head[i..eq]
                .rfind(|c: char| c.is_whitespace())
                .map(|p| i + p + 1)
                .unwrap_or(i);
            let name = head[name_start..eq].trim();
            if bytes.get(eq + 1) == Some(&b'"') {
                if let Some(end) = find_from(bytes, eq + 2, b'"') {
                    let val = unescape(&head[eq + 2..end]);
                    match name {
                        "type" => ty = val,
                        "k" => key = Some(val),
                        _ => {}
                    }
                    i = end + 1;
                    continue;
                }
            }
        }
        break;
    }
    (ty, key)
}
