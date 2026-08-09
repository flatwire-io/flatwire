//! Streaming MessagePack (binary) format for flatwire, mirroring the Python
//! reference. flatwire's binary wire is a stream of concatenated MessagePack
//! values (not a length-prefixed array), so encoding needs no upfront count and
//! decoding reads one value at a time. Wire-compatible with standard MessagePack
//! for the JSON data model (null/bool/int/float/str/bin/array/map); no ext types.
//!
//! Values are `serde_json::Value`, keeping the binary path type-uniform with the
//! JSON and XML paths.

use std::io::{self, Read, Write};

use serde_json::{Map, Value};

// --- encoding --------------------------------------------------------------

fn write_value<W: Write>(w: &mut W, v: &Value) -> io::Result<()> {
    match v {
        Value::Null => w.write_all(&[0xc0]),
        Value::Bool(true) => w.write_all(&[0xc3]),
        Value::Bool(false) => w.write_all(&[0xc2]),
        Value::Number(n) => {
            // Canonical: non-negative -> smallest unsigned; negative -> smallest
            // signed; non-integers -> float64.
            if let Some(u) = n.as_u64() {
                write_uint(w, u)
            } else if let Some(i) = n.as_i64() {
                write_neg_int(w, i)
            } else {
                let f = n.as_f64().unwrap();
                w.write_all(&[0xcb])?;
                w.write_all(&f.to_be_bytes())
            }
        }
        Value::String(s) => write_str(w, s),
        Value::Array(arr) => {
            write_array_header(w, arr.len())?;
            for e in arr {
                write_value(w, e)?;
            }
            Ok(())
        }
        Value::Object(map) => {
            write_map_header(w, map.len())?;
            for (k, val) in map {
                write_str(w, k)?;
                write_value(w, val)?;
            }
            Ok(())
        }
    }
}

fn write_neg_int<W: Write>(w: &mut W, v: i64) -> io::Result<()> {
    // v is always negative here (non-negatives go through write_uint).
    if v >= -32 {
        w.write_all(&[(v & 0xff) as u8])
    } else if v >= -0x80 {
        w.write_all(&[0xd0, v as i8 as u8])
    } else if v >= -0x8000 {
        w.write_all(&[0xd1])?;
        w.write_all(&(v as i16).to_be_bytes())
    } else if v >= -0x8000_0000 {
        w.write_all(&[0xd2])?;
        w.write_all(&(v as i32).to_be_bytes())
    } else {
        w.write_all(&[0xd3])?;
        w.write_all(&v.to_be_bytes())
    }
}

fn write_uint<W: Write>(w: &mut W, v: u64) -> io::Result<()> {
    if v <= 0x7f {
        w.write_all(&[v as u8])
    } else if v <= 0xff {
        w.write_all(&[0xcc, v as u8])
    } else if v <= 0xffff {
        w.write_all(&[0xcd])?;
        w.write_all(&(v as u16).to_be_bytes())
    } else if v <= 0xffff_ffff {
        w.write_all(&[0xce])?;
        w.write_all(&(v as u32).to_be_bytes())
    } else {
        w.write_all(&[0xcf])?;
        w.write_all(&v.to_be_bytes())
    }
}

fn write_str<W: Write>(w: &mut W, s: &str) -> io::Result<()> {
    let body = s.as_bytes();
    let n = body.len();
    if n <= 31 {
        w.write_all(&[0xa0 | n as u8])?;
    } else if n <= 0xff {
        w.write_all(&[0xd9, n as u8])?;
    } else if n <= 0xffff {
        w.write_all(&[0xda])?;
        w.write_all(&(n as u16).to_be_bytes())?;
    } else {
        w.write_all(&[0xdb])?;
        w.write_all(&(n as u32).to_be_bytes())?;
    }
    w.write_all(body)
}

fn write_array_header<W: Write>(w: &mut W, n: usize) -> io::Result<()> {
    if n <= 15 {
        w.write_all(&[0x90 | n as u8])
    } else if n <= 0xffff {
        w.write_all(&[0xdc])?;
        w.write_all(&(n as u16).to_be_bytes())
    } else {
        w.write_all(&[0xdd])?;
        w.write_all(&(n as u32).to_be_bytes())
    }
}

fn write_map_header<W: Write>(w: &mut W, n: usize) -> io::Result<()> {
    if n <= 15 {
        w.write_all(&[0x80 | n as u8])
    } else if n <= 0xffff {
        w.write_all(&[0xde])?;
        w.write_all(&(n as u16).to_be_bytes())
    } else {
        w.write_all(&[0xdf])?;
        w.write_all(&(n as u32).to_be_bytes())
    }
}

/// Stream a collection as concatenated MessagePack values, one per element.
pub fn encode_array<'a, I, W>(items: I, writer: &mut W) -> io::Result<usize>
where
    I: IntoIterator<Item = &'a Value>,
    W: Write,
{
    let mut count = 0usize;
    for v in items {
        write_value(writer, v)?;
        count += 1;
    }
    Ok(count)
}

// --- decoding --------------------------------------------------------------

/// A lazy iterator over concatenated MessagePack values read from a reader.
pub struct MsgPackIter<R: Read> {
    reader: R,
    buf: Vec<u8>,
    pos: usize,
    eof: bool,
    finished: bool,
}

/// Stream concatenated MessagePack values, yielding one at a time.
pub fn decode_array<R: Read>(reader: R) -> MsgPackIter<R> {
    MsgPackIter {
        reader,
        buf: Vec::new(),
        pos: 0,
        eof: false,
        finished: false,
    }
}

impl<R: Read> MsgPackIter<R> {
    fn fill(&mut self, need: usize) -> io::Result<bool> {
        while self.buf.len() - self.pos < need {
            // Drop the consumed prefix so memory stays bounded.
            if self.pos > 0 {
                self.buf.drain(0..self.pos);
                self.pos = 0;
            }
            let mut tmp = [0u8; 65536];
            let k = self.reader.read(&mut tmp)?;
            if k == 0 {
                self.eof = true;
                return Ok(self.buf.len() - self.pos >= need);
            }
            self.buf.extend_from_slice(&tmp[..k]);
        }
        Ok(true)
    }

    fn at_end(&mut self) -> io::Result<bool> {
        if self.pos < self.buf.len() {
            return Ok(false);
        }
        if self.eof {
            return Ok(true);
        }
        Ok(!self.fill(1)?)
    }

    fn take(&mut self, n: usize) -> io::Result<Vec<u8>> {
        if !self.fill(n)? {
            return Err(io::Error::new(
                io::ErrorKind::UnexpectedEof,
                "flatwire msgpack: truncated value",
            ));
        }
        let out = self.buf[self.pos..self.pos + n].to_vec();
        self.pos += n;
        Ok(out)
    }

    fn u8(&mut self) -> io::Result<u8> {
        Ok(self.take(1)?[0])
    }

    fn be16(&mut self) -> io::Result<u16> {
        let b = self.take(2)?;
        Ok(u16::from_be_bytes([b[0], b[1]]))
    }
    fn be32(&mut self) -> io::Result<u32> {
        let b = self.take(4)?;
        Ok(u32::from_be_bytes([b[0], b[1], b[2], b[3]]))
    }
    fn be64(&mut self) -> io::Result<[u8; 8]> {
        let b = self.take(8)?;
        Ok([b[0], b[1], b[2], b[3], b[4], b[5], b[6], b[7]])
    }

    fn read_value(&mut self) -> io::Result<Value> {
        let c = self.u8()?;
        if c <= 0x7f {
            return Ok(Value::from(c as i64));
        }
        if c >= 0xe0 {
            return Ok(Value::from((c as i8) as i64));
        }
        if (0x80..=0x8f).contains(&c) {
            return self.read_map((c & 0x0f) as usize);
        }
        if (0x90..=0x9f).contains(&c) {
            return self.read_array((c & 0x0f) as usize);
        }
        if (0xa0..=0xbf).contains(&c) {
            let s = self.take((c & 0x1f) as usize)?;
            return Ok(Value::String(str_utf8(s)?));
        }
        match c {
            0xc0 => Ok(Value::Null),
            0xc2 => Ok(Value::Bool(false)),
            0xc3 => Ok(Value::Bool(true)),
            0xca => {
                let b = self.take(4)?;
                let f = f32::from_be_bytes([b[0], b[1], b[2], b[3]]) as f64;
                Ok(num_f64(f))
            }
            0xcb => {
                let b = self.be64()?;
                Ok(num_f64(f64::from_be_bytes(b)))
            }
            0xcc => Ok(Value::from(self.u8()? as i64)),
            0xcd => Ok(Value::from(self.be16()? as i64)),
            0xce => Ok(Value::from(self.be32()? as i64)),
            0xcf => Ok(Value::from(u64::from_be_bytes(self.be64()?))),
            0xd0 => Ok(Value::from((self.u8()? as i8) as i64)),
            0xd1 => Ok(Value::from(self.be16()? as i16 as i64)),
            0xd2 => Ok(Value::from(self.be32()? as i32 as i64)),
            0xd3 => Ok(Value::from(i64::from_be_bytes(self.be64()?))),
            0xd9 => {
                let n = self.u8()? as usize;
                let s = self.take(n)?;
                Ok(Value::String(str_utf8(s)?))
            }
            0xda => {
                let n = self.be16()? as usize;
                let s = self.take(n)?;
                Ok(Value::String(str_utf8(s)?))
            }
            0xdb => {
                let n = self.be32()? as usize;
                let s = self.take(n)?;
                Ok(Value::String(str_utf8(s)?))
            }
            0xdc => {
                let n = self.be16()? as usize;
                self.read_array(n)
            }
            0xdd => {
                let n = self.be32()? as usize;
                self.read_array(n)
            }
            0xde => {
                let n = self.be16()? as usize;
                self.read_map(n)
            }
            0xdf => {
                let n = self.be32()? as usize;
                self.read_map(n)
            }
            // bin family -> represent as an array of byte numbers is lossy; the
            // JSON model has no bytes, so we surface bin as a string of raw bytes
            // decoded lossily is wrong. flatwire's JSON model never emits bin, so
            // treat bin as unsupported on decode to stay honest.
            0xc4 | 0xc5 | 0xc6 => Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "flatwire msgpack: binary (bin) type is not part of the JSON value model",
            )),
            _ => Err(io::Error::new(
                io::ErrorKind::InvalidData,
                format!("flatwire msgpack: unknown prefix 0x{c:02x}"),
            )),
        }
    }

    fn read_array(&mut self, n: usize) -> io::Result<Value> {
        let mut arr = Vec::with_capacity(n);
        for _ in 0..n {
            arr.push(self.read_value()?);
        }
        Ok(Value::Array(arr))
    }

    fn read_map(&mut self, n: usize) -> io::Result<Value> {
        let mut map = Map::new();
        for _ in 0..n {
            let k = self.read_value()?;
            let key = match k {
                Value::String(s) => s,
                other => other.to_string(),
            };
            let v = self.read_value()?;
            map.insert(key, v);
        }
        Ok(Value::Object(map))
    }
}

fn str_utf8(b: Vec<u8>) -> io::Result<String> {
    String::from_utf8(b).map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e))
}

fn num_f64(f: f64) -> Value {
    serde_json::Number::from_f64(f)
        .map(Value::Number)
        .unwrap_or(Value::Null)
}

impl<R: Read> Iterator for MsgPackIter<R> {
    type Item = io::Result<Value>;

    fn next(&mut self) -> Option<Self::Item> {
        if self.finished {
            return None;
        }
        match self.at_end() {
            Ok(true) => {
                self.finished = true;
                None
            }
            Ok(false) => Some(self.read_value()),
            Err(e) => {
                self.finished = true;
                Some(Err(e))
            }
        }
    }
}
