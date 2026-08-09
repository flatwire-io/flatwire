use std::io::Cursor;

use flatwire::xml;
use serde_json::json;

#[test]
fn xml_encode_decode_roundtrips_with_types() {
    let items = vec![
        json!({"id": 1, "name": "row-1", "ok": true, "tags": ["a", "b"], "score": 3.5, "note": null}),
        json!({"id": 2, "name": "has < & > \" chars", "ok": false, "nested": {"x": [1, 2, {"y": "z"}]}}),
        json!(42),
        json!("plain"),
        json!([1, 2, 3]),
        json!(null),
        json!(true),
    ];
    let mut buf = Vec::new();
    let n = xml::encode_array(items.iter(), &mut buf, "items").unwrap();
    assert_eq!(n, items.len());

    let out: Vec<_> = xml::decode_array(Cursor::new(buf), "item")
        .map(|r| r.unwrap())
        .collect();
    assert_eq!(out, items);
}

#[test]
fn xml_streams_across_small_reads() {
    // Force element boundaries to land mid-read by using a reader that returns
    // a few bytes at a time.
    struct Trickle {
        data: Vec<u8>,
        pos: usize,
    }
    impl std::io::Read for Trickle {
        fn read(&mut self, out: &mut [u8]) -> std::io::Result<usize> {
            if self.pos >= self.data.len() {
                return Ok(0);
            }
            let n = out.len().min(7).min(self.data.len() - self.pos);
            out[..n].copy_from_slice(&self.data[self.pos..self.pos + n]);
            self.pos += n;
            Ok(n)
        }
    }

    let items: Vec<_> = (0..1000)
        .map(|i| json!({"id": i, "name": format!("row-{i}"), "vals": [i, i + 1]}))
        .collect();
    let mut buf = Vec::new();
    xml::encode_array(items.iter(), &mut buf, "items").unwrap();

    let trickle = Trickle { data: buf, pos: 0 };
    let out: Vec<_> = xml::decode_array(trickle, "item")
        .map(|r| r.unwrap())
        .collect();
    assert_eq!(out, items);
}
