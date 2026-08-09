//! Streaming CBOR (RFC 8949 binary) format for flatwire, mirroring the Python
//! reference. flatwire's CBOR wire is a stream of concatenated CBOR data items
//! (not a length-prefixed array), so encoding needs no upfront count and decoding
//! reads one item at a time. The encoding is deterministic (shortest heads, map
//! keys sorted by UTF-8 bytes, 64-bit floats), so output is byte-identical across
//! all six flatwire languages. Covers the JSON data model
//! (null/bool/int/float/str/array/map); no tags.
//!
//! Values are `serde_json::Value`, keeping the binary path type-uniform with the
//! JSON and XML paths. `serde_json::Map` (a BTreeMap) already iterates keys in
//! UTF-8 byte order, which is exactly the deterministic map-key ordering CBOR
//! requires.

use std::io::{self, Read, Write};

use serde_json::{Map, Value};

// --- encoding --------------------------------------------------------------

fn write_head<W: Write>(w: &mut W, major: u8, n: u64) -> io::Result<()> {
    let mt = major << 5;
    if n < 24 {
        w.write_all(&[mt | n as u8])
    } else if n <= 0xff {
        w.write_all(&[mt | 24, n as u8])
    } else if n <= 0xffff {
        w.write_all(&[mt | 25])?;
        w.write_all(&(n as u16).to_be_bytes())
    } else if n <= 0xffff_ffff {
        w.write_all(&[mt | 26])?;
        w.write_all(&(n as u32).to_be_bytes())
    } else {
        w.write_all(&[mt | 27])?;
        w.write_all(&n.to_be_bytes())
    }
}

fn write_value<W: Write>(w: &mut W, v: &Value) -> io::Result<()> {
    match v {
        Value::Null => w.write_all(&[0xf6]),
        Value::Bool(true) => w.write_all(&[0xf5]),
        Value::Bool(false) => w.write_all(&[0xf4]),
        Value::Number(n) => {
            if let Some(u) = n.as_u64() {
                write_head(w, 0, u)
            } else if let Some(i) = n.as_i64() {
                // i is negative here (non-negatives go through as_u64 above).
                write_head(w, 1, (-1 - i) as u64)
            } else {
                let f = n.as_f64().unwrap();
                w.write_all(&[0xfb])?;
                w.write_all(&f.to_be_bytes())
            }
        }
        Value::String(s) => {
            let body = s.as_bytes();
            write_head(w, 3, body.len() as u64)?;
            w.write_all(body)
        }
        Value::Array(arr) => {
            write_head(w, 4, arr.len() as u64)?;
            for e in arr {
                write_value(w, e)?;
            }
            Ok(())
        }
        Value::Object(map) => {
            write_head(w, 5, map.len() as u64)?;
            // serde_json::Map iterates in sorted (UTF-8 byte) key order already.
            for (k, val) in map {
                let kb = k.as_bytes();
                write_head(w, 3, kb.len() as u64)?;
                w.write_all(kb)?;
                write_value(w, val)?;
            }
            Ok(())
        }
    }
}

/// Stream a collection as concatenated CBOR data items, one per element.
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

/// A lazy iterator over concatenated CBOR data items read from a reader.
pub struct CborIter<R: Read> {
    reader: R,
    buf: Vec<u8>,
    pos: usize,
    eof: bool,
    finished: bool,
}

/// Stream concatenated CBOR data items, yielding one at a time.
pub fn decode_array<R: Read>(reader: R) -> CborIter<R> {
    CborIter {
        reader,
        buf: Vec::new(),
        pos: 0,
        eof: false,
        finished: false,
    }
}

impl<R: Read> CborIter<R> {
    fn fill(&mut self, need: usize) -> io::Result<bool> {
        while self.buf.len() - self.pos < need {
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
                "flatwire cbor: truncated value",
            ));
        }
        let out = self.buf[self.pos..self.pos + n].to_vec();
        self.pos += n;
        Ok(out)
    }

    fn u8(&mut self) -> io::Result<u8> {
        Ok(self.take(1)?[0])
    }

    fn argument(&mut self, ai: u8) -> io::Result<u64> {
        match ai {
            0..=23 => Ok(ai as u64),
            24 => Ok(self.u8()? as u64),
            25 => {
                let b = self.take(2)?;
                Ok(u16::from_be_bytes([b[0], b[1]]) as u64)
            }
            26 => {
                let b = self.take(4)?;
                Ok(u32::from_be_bytes([b[0], b[1], b[2], b[3]]) as u64)
            }
            27 => {
                let b = self.take(8)?;
                Ok(u64::from_be_bytes([
                    b[0], b[1], b[2], b[3], b[4], b[5], b[6], b[7],
                ]))
            }
            _ => Err(io::Error::new(
                io::ErrorKind::InvalidData,
                format!("flatwire cbor: unsupported additional info {ai}"),
            )),
        }
    }

    fn read_value(&mut self) -> io::Result<Value> {
        let ib = self.u8()?;
        let major = ib >> 5;
        let ai = ib & 0x1f;
        match major {
            0 => Ok(Value::from(self.argument(ai)?)),
            1 => {
                let a = self.argument(ai)?;
                // value = -1 - a. Represent within the JSON model (i64 range).
                let n = -1i128 - a as i128;
                if n >= i64::MIN as i128 {
                    Ok(Value::from(n as i64))
                } else {
                    Err(io::Error::new(
                        io::ErrorKind::InvalidData,
                        "flatwire cbor: negative integer out of i64 range",
                    ))
                }
            }
            2 => Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "flatwire cbor: byte-string is not part of the JSON value model",
            )),
            3 => {
                let n = self.argument(ai)? as usize;
                let s = self.take(n)?;
                Ok(Value::String(str_utf8(s)?))
            }
            4 => {
                let n = self.argument(ai)? as usize;
                let mut arr = Vec::with_capacity(n);
                for _ in 0..n {
                    arr.push(self.read_value()?);
                }
                Ok(Value::Array(arr))
            }
            5 => {
                let n = self.argument(ai)? as usize;
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
            7 => match ai {
                20 => Ok(Value::Bool(false)),
                21 => Ok(Value::Bool(true)),
                22 => Ok(Value::Null),
                23 => Ok(Value::Null), // undefined -> null
                25 => {
                    let b = self.take(2)?;
                    Ok(num_f64(decode_f16(u16::from_be_bytes([b[0], b[1]]))))
                }
                26 => {
                    let b = self.take(4)?;
                    Ok(num_f64(f32::from_be_bytes([b[0], b[1], b[2], b[3]]) as f64))
                }
                27 => {
                    let b = self.take(8)?;
                    Ok(num_f64(f64::from_be_bytes([
                        b[0], b[1], b[2], b[3], b[4], b[5], b[6], b[7],
                    ])))
                }
                _ => Err(io::Error::new(
                    io::ErrorKind::InvalidData,
                    format!("flatwire cbor: unsupported simple value {ai}"),
                )),
            },
            _ => Err(io::Error::new(
                io::ErrorKind::InvalidData,
                format!("flatwire cbor: unsupported major type {major}"),
            )),
        }
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

fn decode_f16(h: u16) -> f64 {
    let sign = (h >> 15) & 0x1;
    let exp = (h >> 10) & 0x1f;
    let frac = h & 0x3ff;
    let val = if exp == 0 {
        (frac as f64 / 1024.0) * 2f64.powi(-14)
    } else if exp == 0x1f {
        if frac == 0 {
            f64::INFINITY
        } else {
            f64::NAN
        }
    } else {
        (1.0 + frac as f64 / 1024.0) * 2f64.powi(exp as i32 - 15)
    };
    if sign == 1 {
        -val
    } else {
        val
    }
}

impl<R: Read> Iterator for CborIter<R> {
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
