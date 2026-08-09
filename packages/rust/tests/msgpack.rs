use std::io::Cursor;

use flatwire::msgpack;
use serde_json::json;

#[test]
fn msgpack_encode_decode_roundtrips_with_types() {
    let items = vec![
        json!({"id": 1, "name": "row-1", "ok": true, "tags": ["a", "b"], "score": 3.5, "note": null}),
        json!(42),
        json!(-7),
        json!(300),
        json!(-300),
        json!(100000),
        json!("unïcode ✓ €uro 🎯"),
        json!([1, 2, 3]),
        json!(null),
        json!(true),
        json!(3.14159),
        json!(-1.5),
    ];
    let mut buf = Vec::new();
    let n = msgpack::encode_array(items.iter(), &mut buf).unwrap();
    assert_eq!(n, items.len());

    let out: Vec<_> = msgpack::decode_array(Cursor::new(buf))
        .map(|r| r.unwrap())
        .collect();
    assert_eq!(out, items);
}

#[test]
fn msgpack_is_more_compact_than_json() {
    let items: Vec<_> = (0..1000)
        .map(|i| json!({"id": i, "name": format!("row-{i}"), "ok": i % 2 == 0}))
        .collect();
    let mut mp = Vec::new();
    msgpack::encode_array(items.iter(), &mut mp).unwrap();
    let json = serde_json::to_vec(&items).unwrap();
    assert!(mp.len() < json.len(), "msgpack {} vs json {}", mp.len(), json.len());
}

#[test]
fn msgpack_streams_across_small_reads() {
    struct Trickle {
        data: Vec<u8>,
        pos: usize,
    }
    impl std::io::Read for Trickle {
        fn read(&mut self, out: &mut [u8]) -> std::io::Result<usize> {
            if self.pos >= self.data.len() {
                return Ok(0);
            }
            let n = out.len().min(5).min(self.data.len() - self.pos);
            out[..n].copy_from_slice(&self.data[self.pos..self.pos + n]);
            self.pos += n;
            Ok(n)
        }
    }

    let items: Vec<_> = (0..2000)
        .map(|i| json!({"id": i, "vals": [i, i + 1, i + 2]}))
        .collect();
    let mut buf = Vec::new();
    msgpack::encode_array(items.iter(), &mut buf).unwrap();

    let out: Vec<_> = msgpack::decode_array(Trickle { data: buf, pos: 0 })
        .map(|r| r.unwrap())
        .collect();
    assert_eq!(out, items);
}
