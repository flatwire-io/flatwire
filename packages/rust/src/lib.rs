//! flatwire - streaming JSON serialization that keeps memory flat and time linear.
//!
//! The array helpers are the point: a large collection is written and read one
//! element at a time, so peak memory is bounded by the largest single element
//! rather than the whole collection. Wire format is plain JSON via serde_json.

use std::io::{self, Read, Write};

use serde::Serialize;
use serde_json::Value;

/// Encode a whole value to UTF-8 JSON bytes.
pub fn encode<T: Serialize>(value: &T) -> serde_json::Result<Vec<u8>> {
    serde_json::to_vec(value)
}

/// Decode UTF-8 JSON bytes to a `serde_json::Value`.
pub fn decode(data: &[u8]) -> serde_json::Result<Value> {
    serde_json::from_slice(data)
}

/// Stream a value straight to a writer (no intermediate `String`).
pub fn encode_to<T: Serialize, W: Write>(value: &T, writer: &mut W) -> io::Result<()> {
    serde_json::to_writer(&mut *writer, value).map_err(io::Error::from)
}

/// Read a whole value from a reader.
pub fn decode_from<R: Read>(reader: R) -> serde_json::Result<Value> {
    serde_json::from_reader(reader)
}

/// Stream a large collection as a JSON array, one element at a time. Peak memory
/// is bounded by the largest single element, not the collection length. Returns
/// the number of elements written.
pub fn encode_array<T, I, W>(items: I, writer: &mut W) -> io::Result<usize>
where
    T: Serialize,
    I: IntoIterator<Item = T>,
    W: Write,
{
    writer.write_all(b"[")?;
    let mut count = 0usize;
    for item in items {
        if count > 0 {
            writer.write_all(b",")?;
        }
        serde_json::to_writer(&mut *writer, &item).map_err(io::Error::from)?;
        count += 1;
    }
    writer.write_all(b"]")?;
    Ok(count)
}

/// A lazy iterator over the elements of a top-level JSON array read from a
/// reader. Tracks bracket/brace depth and string state to find element
/// boundaries without materializing the whole array; each element is parsed
/// individually, so memory stays proportional to the largest element.
pub struct ArrayIter<R: Read> {
    reader: R,
    buf: Vec<u8>,
    pos: usize,
    depth: i64,
    max_depth: i64,
    in_string: bool,
    escape: bool,
    started: bool,
    finished: bool,
}

pub fn decode_array<R: Read>(reader: R) -> ArrayIter<R> {
    ArrayIter {
        reader,
        buf: Vec::new(),
        pos: 0,
        depth: 0,
        max_depth: 200,
        in_string: false,
        escape: false,
        started: false,
        finished: false,
    }
}

impl<R: Read> ArrayIter<R> {
    /// Bound how deeply a single element may nest before the iterator rejects the
    /// input, guarding against hostile `[[[[...` streams. Use 0 to disable.
    pub fn with_max_depth(mut self, max_depth: i64) -> Self {
        self.max_depth = max_depth;
        self
    }
}

impl<R: Read> Iterator for ArrayIter<R> {
    type Item = io::Result<Value>;

    fn next(&mut self) -> Option<Self::Item> {
        if self.finished {
            return None;
        }
        // Drop everything already consumed so the buffer never grows with the
        // array. After this, the current element begins at index 0.
        if self.pos > 0 {
            self.buf.drain(0..self.pos);
            self.pos = 0;
        }
        loop {
            while self.pos < self.buf.len() {
                let ch = self.buf[self.pos];
                if !self.started {
                    if ch.is_ascii_whitespace() {
                        self.pos += 1;
                        self.buf.drain(0..self.pos);
                        self.pos = 0;
                        continue;
                    }
                    if ch != b'[' {
                        self.finished = true;
                        return Some(Err(io::Error::new(
                            io::ErrorKind::InvalidData,
                            "decode_array expects a top-level JSON array",
                        )));
                    }
                    self.started = true;
                    self.pos += 1;
                    self.buf.drain(0..self.pos);
                    self.pos = 0;
                    continue;
                }
                if self.in_string {
                    if self.escape {
                        self.escape = false;
                    } else if ch == b'\\' {
                        self.escape = true;
                    } else if ch == b'"' {
                        self.in_string = false;
                    }
                    self.pos += 1;
                    continue;
                }
                match ch {
                    b'"' => self.in_string = true,
                    b'{' | b'[' => {
                        self.depth += 1;
                        if self.max_depth > 0 && self.depth > self.max_depth {
                            self.finished = true;
                            return Some(Err(io::Error::new(
                                io::ErrorKind::InvalidData,
                                "decode_array: nesting depth exceeded",
                            )));
                        }
                    }
                    b']' if self.depth == 0 => {
                        let s = std::str::from_utf8(&self.buf[..self.pos])
                            .unwrap_or("")
                            .trim();
                        self.pos += 1;
                        self.finished = true;
                        if s.is_empty() {
                            return None;
                        }
                        return Some(serde_json::from_str(s).map_err(io::Error::from));
                    }
                    b'}' | b']' => self.depth -= 1,
                    b',' if self.depth == 0 => {
                        let s = std::str::from_utf8(&self.buf[..self.pos])
                            .unwrap_or("")
                            .trim()
                            .to_string();
                        self.pos += 1;
                        return Some(serde_json::from_str(&s).map_err(io::Error::from));
                    }
                    _ => {}
                }
                self.pos += 1;
            }
            // Ran out of buffered bytes mid-element: read more. elem_start is 0,
            // so the whole partial element (bounded by element size) is retained.
            let mut tmp = [0u8; 65536];
            match self.reader.read(&mut tmp) {
                Ok(0) => {
                    self.finished = true;
                    return Some(Err(io::Error::new(
                        io::ErrorKind::UnexpectedEof,
                        "stream ended before the JSON array was closed",
                    )));
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
