use std::io::Cursor;

use flatwire::{decode, decode_array, encode, encode_array};
use serde_json::json;

#[test]
fn encode_decode_roundtrip() {
    let value = json!({"a": 1, "b": [1, 2, 3], "s": "héllo \" world"});
    let bytes = encode(&value).unwrap();
    assert_eq!(decode(&bytes).unwrap(), value);
}

#[test]
fn encode_array_then_decode_array_roundtrips() {
    let items: Vec<_> = (0..1000)
        .map(|i| json!({"id": i, "name": format!("row-{i}"), "ok": i % 2 == 0}))
        .collect();
    let mut buf = Vec::new();
    let n = encode_array(items.iter(), &mut buf).unwrap();
    assert_eq!(n, 1000);

    // Valid ordinary JSON array.
    let whole: serde_json::Value = serde_json::from_slice(&buf).unwrap();
    assert_eq!(whole.as_array().unwrap().len(), 1000);

    // decode_array streams every element back.
    let out: Vec<_> = decode_array(Cursor::new(buf)).map(|r| r.unwrap()).collect();
    assert_eq!(out, items);
}

#[test]
fn decode_array_handles_nested_and_tricky_strings() {
    let tricky = vec![
        json!({"s": "has, comma and ] bracket and \" quote"}),
        json!([1, [2, 3], {"k": "v,]["}]),
        json!("plain"),
        json!(42),
        json!(null),
    ];
    let bytes = encode(&tricky).unwrap();
    let out: Vec<_> = decode_array(Cursor::new(bytes)).map(|r| r.unwrap()).collect();
    assert_eq!(out, tricky);
}

#[test]
fn decode_array_is_lazy() {
    let items: Vec<i64> = (0..10_000).collect();
    let bytes = encode(&items).unwrap();
    let mut it = decode_array(Cursor::new(bytes));
    assert_eq!(it.next().unwrap().unwrap(), json!(0));
    assert_eq!(it.next().unwrap().unwrap(), json!(1));
}

#[test]
fn decode_array_rejects_non_array() {
    let bytes = b"{\"not\": \"array\"}".to_vec();
    let first = decode_array(Cursor::new(bytes)).next().unwrap();
    assert!(first.is_err());
}
