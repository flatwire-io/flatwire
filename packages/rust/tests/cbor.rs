use std::io::Cursor;

use flatwire::cbor::{decode_array, encode_array};
use serde_json::json;

#[test]
fn cbor_encode_array_then_decode_array_roundtrips() {
    let items: Vec<_> = (0..1000)
        .map(|i| json!({"id": i, "name": format!("row-{i}"), "ok": i % 2 == 0, "tags": ["a", "b"], "note": null}))
        .collect();
    let mut buf = Vec::new();
    let n = encode_array(items.iter(), &mut buf).unwrap();
    assert_eq!(n, 1000);

    let out: Vec<_> = decode_array(Cursor::new(&buf)).map(|r| r.unwrap()).collect();
    assert_eq!(out, items);
}

#[test]
fn cbor_preserves_types_and_unicode() {
    let items = vec![
        json!(42),
        json!(-7),
        json!(300),
        json!(-300),
        json!(100000),
        json!(3.14159),
        json!(-1.5),
        json!(true),
        json!(false),
        json!(null),
        json!("unïcode ✓ €uro 🎯"),
        json!([1, [2, 3], {"k": "v"}]),
        json!({"nested": {"deep": [null, true, "x"]}}),
    ];
    let mut buf = Vec::new();
    encode_array(items.iter(), &mut buf).unwrap();
    let out: Vec<_> = decode_array(Cursor::new(&buf)).map(|r| r.unwrap()).collect();
    assert_eq!(out, items);
}

#[test]
fn cbor_canonical_known_vectors() {
    // Deterministic CBOR bytes shared by every flatwire language.
    fn enc(v: serde_json::Value) -> String {
        let mut buf = Vec::new();
        encode_array([&v].into_iter(), &mut buf).unwrap();
        buf.iter().map(|b| format!("{b:02x}")).collect()
    }
    assert_eq!(enc(json!(0)), "00");
    assert_eq!(enc(json!(23)), "17");
    assert_eq!(enc(json!(24)), "1818");
    assert_eq!(enc(json!(255)), "18ff");
    assert_eq!(enc(json!(256)), "190100");
    assert_eq!(enc(json!(-1)), "20");
    assert_eq!(enc(json!(-24)), "37");
    assert_eq!(enc(json!(-25)), "3818");
    assert_eq!(enc(json!(true)), "f5");
    assert_eq!(enc(json!(false)), "f4");
    assert_eq!(enc(json!(null)), "f6");
    assert_eq!(enc(json!("a")), "6161");
    assert_eq!(enc(json!([1, 2, 3])), "83010203");
    // Map keys sorted by UTF-8 bytes: "a" before "b".
    assert_eq!(enc(json!({"b": 2, "a": 1})), "a2616101616202");
    // Float always 64-bit.
    assert_eq!(enc(json!(1.5)), "fb3ff8000000000000");
}

#[test]
fn cbor_is_more_compact_than_json() {
    let items: Vec<_> = (0..1000)
        .map(|i| json!({"id": i, "name": format!("row-{i}"), "ok": i % 2 == 0}))
        .collect();
    let mut jb = Vec::new();
    flatwire::encode_array(items.iter(), &mut jb).unwrap();
    let mut cb = Vec::new();
    encode_array(items.iter(), &mut cb).unwrap();
    assert!(cb.len() < jb.len());
}
