use std::io::Cursor;

use flatwire::checked::{decode_checked_array, encode_checked_array, CheckedError};
use serde_json::{json, Value};

#[test]
fn clean_completion_yields_all_items() {
    let items: Vec<_> = (0..500).map(|i| json!({"id": i})).collect();
    let mut buf = Vec::new();
    let n = encode_checked_array(items.iter(), &mut buf).unwrap();
    assert_eq!(n, 500);

    let mut out = Vec::new();
    for r in decode_checked_array(Cursor::new(&buf)) {
        out.push(r.expect("clean stream must not error"));
    }
    assert_eq!(out.len(), 500);
    assert_eq!(out[499], json!({"id": 499}));
}

#[test]
fn producer_error_surfaces_after_n_items() {
    // Reference wire form: two items then an error trailer.
    let wire = r#"{"items":[1,2],"complete":false,"error":{"message":"boom","type":"ValueError"}}"#;
    let mut ok = Vec::new();
    let mut stream_err: Option<Value> = None;
    for r in decode_checked_array(Cursor::new(wire.as_bytes())) {
        match r {
            Ok(v) => ok.push(v),
            Err(CheckedError::Stream(e)) => stream_err = Some(e),
            Err(e) => panic!("unexpected error: {e}"),
        }
    }
    assert_eq!(ok, vec![json!(1), json!(2)]);
    assert_eq!(
        stream_err.unwrap().get("message").and_then(|m| m.as_str()),
        Some("boom")
    );
}

#[test]
fn truncation_is_detected() {
    let mut buf = Vec::new();
    encode_checked_array([1, 2, 3, 4].iter(), &mut buf).unwrap();
    // Drop the whole terminal status so the closing ] is never seen.
    let terminal = br#"],"complete":true}"#;
    buf.truncate(buf.len() - terminal.len());

    let mut truncated = false;
    for r in decode_checked_array(Cursor::new(&buf)) {
        if let Err(CheckedError::Truncated(_)) = r {
            truncated = true;
        }
    }
    assert!(truncated, "expected a truncation error");
}

#[test]
fn round_trips_error_free_after_last_element() {
    // Ensure the final element before ] is never dropped even on a clean stream.
    let mut buf = Vec::new();
    encode_checked_array([json!({"k": "v"})].iter(), &mut buf).unwrap();
    let out: Vec<_> = decode_checked_array(Cursor::new(&buf))
        .map(|r| r.unwrap())
        .collect();
    assert_eq!(out, vec![json!({"k": "v"})]);
}
