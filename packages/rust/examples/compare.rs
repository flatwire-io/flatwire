//! Head-to-head Rust benchmark: `serde_json` materialized vs flatwire streaming,
//! measuring BOTH peak heap bytes and wall-clock time.
//!
//! Peak memory is measured with a custom tracking global allocator - the accurate
//! way in Rust, which has no built-in per-operation allocation counter. The
//! allocator records current and peak live bytes; each scenario resets the peak
//! to the current baseline, runs once, and reports the delta.
//!
//! Run:  cargo run --release --example compare

use std::alloc::{GlobalAlloc, Layout, System};
use std::io::Cursor;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::time::Instant;

use flatwire::{decode_array, encode_array};
use serde_json::{json, Value};

// ---- tracking allocator ---------------------------------------------------

struct Tracking;

static LIVE: AtomicUsize = AtomicUsize::new(0);
static PEAK: AtomicUsize = AtomicUsize::new(0);

unsafe impl GlobalAlloc for Tracking {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        let ptr = System.alloc(layout);
        if !ptr.is_null() {
            let now = LIVE.fetch_add(layout.size(), Ordering::Relaxed) + layout.size();
            PEAK.fetch_max(now, Ordering::Relaxed);
        }
        ptr
    }
    unsafe fn dealloc(&self, ptr: *mut u8, layout: Layout) {
        LIVE.fetch_sub(layout.size(), Ordering::Relaxed);
        System.dealloc(ptr, layout);
    }
}

#[global_allocator]
static GLOBAL: Tracking = Tracking;

/// Run `f`, returning (result, peak bytes allocated above the entry baseline).
fn peak_of<T>(f: impl FnOnce() -> T) -> (T, usize) {
    let base = LIVE.load(Ordering::Relaxed);
    PEAK.store(base, Ordering::Relaxed);
    let out = f();
    let peak = PEAK.load(Ordering::Relaxed);
    (out, peak.saturating_sub(base))
}

fn median_time(mut f: impl FnMut(), iters: usize) -> f64 {
    f(); // warm up
    let mut samples = Vec::with_capacity(iters);
    for _ in 0..iters {
        let t0 = Instant::now();
        f();
        samples.push(t0.elapsed().as_secs_f64());
    }
    samples.sort_by(|a, b| a.partial_cmp(b).unwrap());
    samples[samples.len() / 2]
}

fn human(n: usize) -> String {
    let units = ["B", "KB", "MB", "GB"];
    let mut v = n as f64;
    let mut i = 0;
    while v >= 1024.0 && i < units.len() - 1 {
        v /= 1024.0;
        i += 1;
    }
    if i == 0 {
        format!("{v:.0}{}", units[i])
    } else {
        format!("{v:.1}{}", units[i])
    }
}

struct NullSink;
impl std::io::Write for NullSink {
    fn write(&mut self, buf: &[u8]) -> std::io::Result<usize> {
        Ok(buf.len())
    }
    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}

fn make_records(n: usize) -> Vec<Value> {
    (0..n)
        .map(|i| json!({"id": i, "name": format!("row-{i}"), "payload": "x".repeat(200), "ok": i % 2 == 0}))
        .collect()
}

fn main() {
    println!("Rust benchmark: serde_json materialized vs flatwire streaming\n");
    println!(
        "{:>9} {:>9} | {:>12} {:>12} | {:>12} {:>12}",
        "elements", "payload", "enc whole", "enc stream", "agg whole", "agg stream"
    );
    println!("{}", "-".repeat(76));

    for n in [1_000usize, 10_000, 50_000] {
        let items = make_records(n);
        let blob = serde_json::to_vec(&items).unwrap();
        let size = blob.len();

        // Encode: materialize a Vec<u8> vs stream element-by-element to a sink.
        let (_, enc_whole_peak) = peak_of(|| serde_json::to_vec(&items).unwrap());
        let (_, enc_stream_peak) = peak_of(|| {
            let mut sink = NullSink;
            encode_array(items.iter(), &mut sink).unwrap();
        });

        // Decode-and-aggregate: parse whole Vec<Value> vs stream one at a time.
        let (_, agg_whole_peak) = peak_of(|| {
            let v: Vec<Value> = serde_json::from_slice(&blob).unwrap();
            v.iter().filter_map(|r| r.get("id")?.as_i64()).sum::<i64>()
        });
        let (_, agg_stream_peak) = peak_of(|| {
            let mut total = 0i64;
            for r in decode_array(Cursor::new(&blob)) {
                let r = r.unwrap();
                total += r.get("id").and_then(|x| x.as_i64()).unwrap_or(0);
            }
            total
        });

        println!(
            "{:>9} {:>9} | {:>12} {:>12} | {:>12} {:>12}",
            n,
            human(size),
            human(enc_whole_peak),
            human(enc_stream_peak),
            human(agg_whole_peak),
            human(agg_stream_peak),
        );

        // Time (only for the largest size, to keep output compact).
        if n == 50_000 {
            let enc_whole_t = median_time(|| { serde_json::to_vec(&items).unwrap(); }, 5);
            let enc_stream_t = median_time(|| {
                let mut s = NullSink;
                encode_array(items.iter(), &mut s).unwrap();
            }, 5);
            let agg_whole_t = median_time(|| {
                let v: Vec<Value> = serde_json::from_slice(&blob).unwrap();
                let _: i64 = v.iter().filter_map(|r| r.get("id")?.as_i64()).sum();
            }, 5);
            let agg_stream_t = median_time(|| {
                let mut total = 0i64;
                for r in decode_array(Cursor::new(&blob)) {
                    total += r.unwrap().get("id").and_then(|x| x.as_i64()).unwrap_or(0);
                }
                let _ = total;
            }, 5);
            println!(
                "\ntime @50k (s): enc_whole={:.4} enc_stream={:.4} agg_whole={:.4} agg_stream={:.4}",
                enc_whole_t, enc_stream_t, agg_whole_t, agg_stream_t
            );
        }
    }
}
