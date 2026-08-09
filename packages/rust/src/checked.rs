//! Partial-stream failure semantics for flatwire (checked streams), matching the
//! Python/Node reference. A streamed collection is wrapped in an envelope whose
//! terminal status is written LAST:
//!
//! ```text
//!   {"items":[ e0, e1, ... ],"complete":true}
//!   {"items":[ e0, e1, ... ],"complete":false,"error":{"message":"...","type":"..."}}
//! ```
//!
//! so a consumer can tell clean completion, an in-band producer error after N
//! rows, and truncation apart. The wire is plain JSON, so a checked stream
//! written by any flatwire language decodes here and vice versa. See
//! `docs/FAILURE.md`.

use std::io::{self, Read, Write};

use serde::Serialize;
use serde_json::Value;

/// Outcome of iterating a [`CheckedArrayIter`] to its end, delivered as the
/// terminal `Err` variants so a consumer can distinguish the three cases.
#[derive(Debug)]
pub enum CheckedError {
    /// The producer finished the stream with `complete:false`; carries the
    /// decoded error payload written on the wire.
    Stream(Value),
    /// The stream ended before a terminal status was written.
    Truncated(String),
    /// The bytes were not a flatwire checked stream, or an element failed to
    /// parse.
    Io(io::Error),
}

impl std::fmt::Display for CheckedError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            CheckedError::Stream(v) => write!(f, "stream error: {v}"),
            CheckedError::Truncated(m) => write!(f, "truncated stream: {m}"),
            CheckedError::Io(e) => write!(f, "{e}"),
        }
    }
}

impl std::error::Error for CheckedError {}

impl From<io::Error> for CheckedError {
    fn from(e: io::Error) -> Self {
        CheckedError::Io(e)
    }
}

/// Stream `items` inside a checked envelope, writing the terminal status last. If
/// serializing an element fails, a `complete:false` trailer carrying the error is
/// written before the error is returned, so the consumer can distinguish failure
/// from truncation. Returns the number of elements written.
pub fn encode_checked_array<T, I, W>(items: I, writer: &mut W) -> io::Result<usize>
where
    T: Serialize,
    I: IntoIterator<Item = T>,
    W: Write,
{
    writer.write_all(b"{\"items\":[")?;
    let mut count = 0usize;
    for item in items {
        if count > 0 {
            writer.write_all(b",")?;
        }
        match serde_json::to_vec(&item) {
            Ok(bytes) => writer.write_all(&bytes)?,
            Err(e) => {
                let err = serde_json::json!({"message": e.to_string(), "type": "SerializeError"});
                writer.write_all(b"],\"complete\":false,\"error\":")?;
                writer.write_all(&serde_json::to_vec(&err).unwrap_or_default())?;
                writer.write_all(b"}")?;
                return Err(io::Error::from(e));
            }
        }
        count += 1;
    }
    writer.write_all(b"],\"complete\":true}")?;
    Ok(count)
}

/// A lazy iterator over the elements of a checked envelope. Each `next()` yields
/// `Ok(Value)` per element; after the last element the iterator enforces the
/// terminal status, yielding `Err(CheckedError::Stream)` if the producer
/// signalled `complete:false` or `Err(CheckedError::Truncated)` if the stream
/// ended without a terminal status. A clean stream ends with `None` and no error.
pub struct CheckedArrayIter<R: Read> {
    reader: R,
    buf: Vec<u8>,
    pos: usize,
    depth: i64,
    max_depth: i64,
    in_string: bool,
    escape: bool,
    header_done: bool,
    finished: bool,
    eof: bool,
    /// A terminal error queued behind a final element, surfaced on the next call.
    pending: Option<Result<Value, CheckedError>>,
}

pub fn decode_checked_array<R: Read>(reader: R) -> CheckedArrayIter<R> {
    CheckedArrayIter {
        reader,
        buf: Vec::new(),
        pos: 0,
        depth: 0,
        max_depth: 200,
        in_string: false,
        escape: false,
        header_done: false,
        finished: false,
        eof: false,
        pending: None,
    }
}

impl<R: Read> CheckedArrayIter<R> {
    /// Bound how deeply a single element may nest before the iterator rejects the
    /// input. Use 0 to disable.
    pub fn with_max_depth(mut self, max_depth: i64) -> Self {
        self.max_depth = max_depth;
        self
    }

    fn more(&mut self) -> bool {
        if self.eof {
            return false;
        }
        let mut tmp = [0u8; 65536];
        match self.reader.read(&mut tmp) {
            Ok(0) => {
                self.eof = true;
                false
            }
            Ok(k) => {
                self.buf.extend_from_slice(&tmp[..k]);
                true
            }
            Err(_) => {
                self.eof = true;
                false
            }
        }
    }

    fn ensure_header(&mut self) -> Result<(), CheckedError> {
        const HEADER: &[u8] = b"{\"items\":[";
        while self.buf.len() < HEADER.len() {
            if !self.more() {
                return Err(CheckedError::Truncated(
                    "stream ended before items array".into(),
                ));
            }
        }
        if &self.buf[..HEADER.len()] != HEADER {
            return Err(CheckedError::Io(io::Error::new(
                io::ErrorKind::InvalidData,
                "decode_checked_array: not a flatwire checked stream",
            )));
        }
        self.buf.drain(0..HEADER.len());
        self.header_done = true;
        Ok(())
    }

    fn finish(&mut self) -> Option<Result<Value, CheckedError>> {
        // Read the remaining (small, bounded) trailer fully.
        while self.more() {}
        let trailer = std::str::from_utf8(&self.buf[self.pos..])
            .unwrap_or("")
            .trim();
        if trailer.is_empty() {
            return Some(Err(CheckedError::Truncated(
                "stream ended before terminal status".into(),
            )));
        }
        let body = trailer.strip_prefix(',').unwrap_or(trailer);
        let obj: Value = match serde_json::from_str(&format!("{{{body}")) {
            Ok(v) => v,
            Err(e) => return Some(Err(CheckedError::Io(io::Error::from(e)))),
        };
        match obj.get("complete") {
            None => Some(Err(CheckedError::Truncated(
                "stream ended before terminal status".into(),
            ))),
            Some(Value::Bool(true)) => None,
            _ => {
                let err = obj
                    .get("error")
                    .cloned()
                    .unwrap_or_else(|| Value::String("unknown stream error".into()));
                Some(Err(CheckedError::Stream(err)))
            }
        }
    }
}

impl<R: Read> Iterator for CheckedArrayIter<R> {
    type Item = Result<Value, CheckedError>;

    fn next(&mut self) -> Option<Self::Item> {
        // A terminal error queued behind the final element is surfaced first.
        if let Some(p) = self.pending.take() {
            self.finished = true;
            return Some(p);
        }
        if self.finished {
            return None;
        }
        if !self.header_done {
            if let Err(e) = self.ensure_header() {
                self.finished = true;
                return Some(Err(e));
            }
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
                            return Some(Err(CheckedError::Io(io::Error::new(
                                io::ErrorKind::InvalidData,
                                "decode_checked_array: nesting depth exceeded",
                            ))));
                        }
                    }
                    b']' if self.depth == 0 => {
                        let s = std::str::from_utf8(&self.buf[..self.pos])
                            .unwrap_or("")
                            .trim()
                            .to_string();
                        self.pos += 1;
                        if s.is_empty() {
                            // No trailing element: the terminal status is the result.
                            self.finished = true;
                            return self.finish();
                        }
                        // A trailing element precedes the terminal status. Yield it
                        // now; if the terminal status signals an error, queue that so
                        // it surfaces on the next call (never dropping the element).
                        let parsed = serde_json::from_str::<Value>(&s)
                            .map_err(|e| CheckedError::Io(io::Error::from(e)));
                        match parsed {
                            Err(e) => {
                                self.finished = true;
                                return Some(Err(e));
                            }
                            Ok(v) => {
                                match self.finish() {
                                    None => self.finished = true,
                                    Some(err) => self.pending = Some(err),
                                }
                                return Some(Ok(v));
                            }
                        }
                    }
                    b'}' | b']' => self.depth -= 1,
                    b',' if self.depth == 0 => {
                        let s = std::str::from_utf8(&self.buf[..self.pos])
                            .unwrap_or("")
                            .trim()
                            .to_string();
                        self.pos += 1;
                        return Some(
                            serde_json::from_str(&s)
                                .map_err(|e| CheckedError::Io(io::Error::from(e))),
                        );
                    }
                    _ => {}
                }
                self.pos += 1;
            }
            if !self.more() {
                self.finished = true;
                return Some(Err(CheckedError::Truncated(
                    "stream ended inside items array".into(),
                )));
            }
        }
    }
}
