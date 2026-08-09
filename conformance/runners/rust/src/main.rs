// flatwire conformance runner (Rust). Encodes+decodes every corpus case in every
// format, records round-trip and a SHA-256 of the encoded bytes -> results/rust.json.

use std::io::Cursor;
use std::path::PathBuf;

use flatwire::{cbor, msgpack, xml};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

fn corpus_root() -> PathBuf {
    // Walk up from the manifest dir to find conformance/corpus.json.
    let mut dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    loop {
        if dir.join("corpus.json").exists() {
            return dir;
        }
        if !dir.pop() {
            panic!("could not locate corpus.json");
        }
    }
}

fn hex(bytes: &[u8]) -> String {
    let mut s = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        s.push_str(&format!("{b:02x}"));
    }
    s
}

fn encode(elements: &[Value], fmt: &str) -> std::io::Result<Vec<u8>> {
    let mut buf = Vec::new();
    match fmt {
        "json" => {
            // flatwire's Rust JSON encode_array takes serde Serialize items.
            flatwire::encode_array(elements.iter(), &mut buf)?;
        }
        "xml" => {
            xml::encode_array(elements.iter(), &mut buf, "items")?;
        }
        "msgpack" => {
            msgpack::encode_array(elements.iter(), &mut buf)?;
        }
        "cbor" => {
            cbor::encode_array(elements.iter(), &mut buf)?;
        }
        _ => unreachable!(),
    }
    Ok(buf)
}

fn decode(data: Vec<u8>, fmt: &str) -> std::io::Result<Vec<Value>> {
    match fmt {
        "json" => flatwire::decode_array(Cursor::new(data))
            .map(|r| r.map_err(std::io::Error::from))
            .collect(),
        "xml" => xml::decode_array(Cursor::new(data), "item").collect(),
        "msgpack" => msgpack::decode_array(Cursor::new(data)).collect(),
        "cbor" => cbor::decode_array(Cursor::new(data)).collect(),
        _ => unreachable!(),
    }
}

fn main() {
    let root = corpus_root();
    let corpus: Value =
        serde_json::from_str(&std::fs::read_to_string(root.join("corpus.json")).unwrap()).unwrap();
    let formats = ["json", "xml", "msgpack", "cbor"];

    let mut cases = serde_json::Map::new();
    let mut passed = 0usize;
    let mut total = 0usize;

    for case in corpus["cases"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap().to_string();
        let tier = case["tier"].as_str().unwrap().to_string();
        let elements: Vec<Value> = case["elements"].as_array().unwrap().clone();

        let mut fmt_results = serde_json::Map::new();
        for fmt in formats {
            total += 1;
            let entry = match encode(&elements, fmt).and_then(|data| {
                let sha = hex(&Sha256::digest(&data));
                let len = data.len();
                let out = decode(data, fmt)?;
                Ok((out == elements, sha, len))
            }) {
                Ok((rt, sha, len)) => {
                    if rt {
                        passed += 1;
                    }
                    json!({"roundtrip": rt, "sha256": sha, "bytes": len})
                }
                Err(e) => json!({"roundtrip": false, "error": e.to_string()}),
            };
            fmt_results.insert(fmt.to_string(), entry);
        }
        cases.insert(name, json!({"tier": tier, "formats": fmt_results}));
    }

    let results = json!({"lang": "rust", "tested_locally": true, "cases": cases});
    let out_path = root.join("results").join("rust.json");
    std::fs::create_dir_all(out_path.parent().unwrap()).unwrap();
    std::fs::write(&out_path, serde_json::to_string_pretty(&results).unwrap()).unwrap();
    println!(
        "rust conformance: {passed}/{total} round-trip; wrote {}",
        out_path.display()
    );
}
