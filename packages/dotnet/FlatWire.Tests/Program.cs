using System.Text;
using System.Text.Json;
using FlatWire;

// A dependency-free assertion runner so the suite builds and runs with just the
// SDK (no NuGet restore). The published package/CI additionally runs it under a
// standard test framework.

int failures = 0;
void Check(string name, bool ok)
{
    Console.WriteLine((ok ? "PASS " : "FAIL ") + name);
    if (!ok) failures++;
}

var value = new Dictionary<string, object> { ["a"] = 1, ["b"] = new[] { 1, 2, 3 } };
byte[] enc = Flat.Encode(value);
var back = Flat.Decode<Dictionary<string, JsonElement>>(enc);
Check("encode/decode roundtrip", back != null && back["a"].GetInt32() == 1);

// Byte-compatible with System.Text.Json defaults.
Check("encode byte-compatible",
    Encoding.UTF8.GetString(Flat.Encode(new { x = new[] { 1, 2, 3 }, y = "text" }))
        == "{\"x\":[1,2,3],\"y\":\"text\"}");

// EncodeArray -> valid JSON array, and DecodeArray streams it back.
var items = Enumerable.Range(0, 1000).Select(i => new Row(i, $"row-{i}", i % 2 == 0)).ToList();
using var ms = new MemoryStream();
long n = Flat.EncodeArray(items, ms);
Check("encodeArray count", n == 1000);

ms.Position = 0;
var whole = Flat.Decode<List<Row>>(ms.ToArray());
Check("encodeArray produces a valid array", whole != null && whole.Count == 1000 && whole[500].Name == "row-500");

ms.Position = 0;
var streamed = new List<Row>();
await foreach (var r in Flat.DecodeArray<Row>(ms))
    if (r != null) streamed.Add(r);
Check("decodeArray streams every element", streamed.Count == 1000 && streamed[999].Id == 999);

// Strings containing commas and brackets must survive the round trip.
var tricky = new[] { "has, comma and ] bracket", "plain", "v,][" };
using var ms2 = new MemoryStream();
Flat.EncodeArray(tricky, ms2);
ms2.Position = 0;
var trickyOut = new List<string>();
await foreach (var s in Flat.DecodeArray<string>(ms2))
    if (s != null) trickyOut.Add(s);
Check("decodeArray handles tricky strings", trickyOut.SequenceEqual(tricky));

// --- XML format ---
// Round-trip a typed object graph through streaming XML.
var xmlItems = new List<object?>
{
    new Dictionary<string, object?> { ["id"] = 1L, ["name"] = "row-1", ["ok"] = true, ["tags"] = new List<object?> { "a", "b" }, ["score"] = 3.5, ["note"] = null },
    new Dictionary<string, object?> { ["id"] = 2L, ["name"] = "has < & > \" chars", ["ok"] = false },
    42L, "plain", new List<object?> { 1L, 2L, 3L }, null, true,
};
using var xms = new MemoryStream();
long xn = FlatXml.EncodeArray(xmlItems, xms);
Check("xml encodeArray count", xn == xmlItems.Count);
xms.Position = 0;
var xmlOut = FlatXml.DecodeArray(xms).ToList();
Check("xml round-trips element count", xmlOut.Count == xmlItems.Count);
Check("xml preserves scalar types", xmlOut[2] is long l && l == 42L && xmlOut[6] is bool b && b);
Check("xml preserves nested object",
    xmlOut[0] is Dictionary<string, object?> d0
    && (long)d0["id"]! == 1L
    && d0["note"] == null
    && d0["tags"] is List<object?> tg && (string)tg[0]! == "a");
Check("xml escapes special chars",
    xmlOut[1] is Dictionary<string, object?> d1 && (string)d1["name"]! == "has < & > \" chars");

// --- MessagePack (binary) format ---
var mpItems = new List<object?>
{
    new Dictionary<string, object?> { ["id"] = 1L, ["name"] = "row-1", ["ok"] = true, ["tags"] = new List<object?> { "a", "b" }, ["score"] = 3.5, ["note"] = null },
    42L, -7L, 300L, -300L, 100000L, "unïcode ✓ €", new List<object?> { 1L, 2L, 3L }, null, true, 3.14159, -1.5,
};
using var mpms = new MemoryStream();
long mpn = FlatMsgPack.EncodeArray(mpItems, mpms);
Check("msgpack encodeArray count", mpn == mpItems.Count);
mpms.Position = 0;
var mpOut = FlatMsgPack.DecodeArray(mpms).ToList();
Check("msgpack round-trips element count", mpOut.Count == mpItems.Count);
Check("msgpack preserves ints and floats",
    mpOut[1] is long m1 && m1 == 42L && mpOut[2] is long m2 && m2 == -7L
    && mpOut[10] is double m10 && Math.Abs(m10 - 3.14159) < 1e-9);
Check("msgpack preserves nested object + unicode",
    mpOut[0] is Dictionary<string, object?> md && (long)md["id"]! == 1L
    && (string)md["name"]! == "row-1" && md["note"] == null
    && mpOut[6] is string u && u == "unïcode ✓ €");
// msgpack is more compact than JSON for a records shape.
var compactItems = Enumerable.Range(0, 1000).Select(i => (object?)new Dictionary<string, object?> { ["id"] = (long)i, ["name"] = $"row-{i}", ["ok"] = i % 2 == 0 }).ToList();
using var jjs = new MemoryStream(); using var mmp = new MemoryStream();
foreach (var it in compactItems) { } // no-op to keep it explicit
var jsonBytes = Encoding.UTF8.GetBytes(JsonSerializer.Serialize(compactItems));
FlatMsgPack.EncodeArray(compactItems, mmp);
Check("msgpack smaller than json", mmp.Length < jsonBytes.Length);

// Wire-compat: if a reference Python-encoded stream is present (produced during
// local cross-checks), verify .NET is byte-identical and can decode it. Skipped
// on CI where the file is absent — the self-contained checks above still run.
var pyPath = Path.Combine(Environment.GetEnvironmentVariable("TEMP") ?? ".", "mp_from_py.bin");
if (File.Exists(pyPath))
{
    using var cms = new MemoryStream();
    FlatMsgPack.EncodeArray(mpItems, cms);
    var py = File.ReadAllBytes(pyPath);
    Check("msgpack wire-identical to Python", cms.ToArray().SequenceEqual(py));
    using var pms = new MemoryStream(py);
    Check("msgpack decodes Python stream", FlatMsgPack.DecodeArray(pms).Count() == 12);
}

// --- CBOR (binary) format ---
var cborItems = new List<object?>
{
    new Dictionary<string, object?> { ["id"] = 1L, ["name"] = "row-1", ["ok"] = true, ["tags"] = new List<object?> { "a", "b" }, ["score"] = 3.5, ["note"] = null },
    42L, -7L, 300L, -300L, 100000L, "unïcode ✓ €", new List<object?> { 1L, 2L, 3L }, null, true, 3.14159, -1.5,
};
using var cbms = new MemoryStream();
long cbn = FlatCbor.EncodeArray(cborItems, cbms);
Check("cbor encodeArray count", cbn == cborItems.Count);
cbms.Position = 0;
var cbOut = FlatCbor.DecodeArray(cbms).ToList();
Check("cbor round-trips element count", cbOut.Count == cborItems.Count);
Check("cbor preserves ints and floats",
    cbOut[1] is long cb1 && cb1 == 42L && cbOut[2] is long cb2 && cb2 == -7L
    && cbOut[10] is double cb10 && Math.Abs(cb10 - 3.14159) < 1e-9);
Check("cbor preserves nested object + unicode",
    cbOut[0] is Dictionary<string, object?> cbd && (long)cbd["id"]! == 1L
    && (string)cbd["name"]! == "row-1" && cbd["note"] == null
    && cbOut[6] is string cu && cu == "unïcode ✓ €");
// Canonical known vectors: identical bytes to the Python/Node reference.
static string CborHex(object? v)
{
    using var m = new MemoryStream();
    FlatCbor.EncodeArray(new List<object?> { v }, m);
    return Convert.ToHexString(m.ToArray()).ToLowerInvariant();
}
Check("cbor canonical int vectors",
    CborHex(0L) == "00" && CborHex(23L) == "17" && CborHex(24L) == "1818"
    && CborHex(255L) == "18ff" && CborHex(256L) == "190100"
    && CborHex(-1L) == "20" && CborHex(-24L) == "37" && CborHex(-25L) == "3818");
Check("cbor canonical map/array/float vectors",
    CborHex(new List<object?> { 1L, 2L, 3L }) == "83010203"
    && CborHex(new Dictionary<string, object?> { ["b"] = 2L, ["a"] = 1L }) == "a2616101616202"
    && CborHex(1.5) == "fb3ff8000000000000");
// cbor is more compact than JSON for a records shape.
var cborCompact = Enumerable.Range(0, 1000).Select(i => (object?)new Dictionary<string, object?> { ["id"] = (long)i, ["name"] = $"row-{i}", ["ok"] = i % 2 == 0 }).ToList();
using var cbcmp = new MemoryStream();
FlatCbor.EncodeArray(cborCompact, cbcmp);
Check("cbor smaller than json", cbcmp.Length < Encoding.UTF8.GetBytes(JsonSerializer.Serialize(cborCompact)).Length);

// --- Checked streams (partial-stream failure semantics) ---
// Clean completion: decode yields all rows and does not throw.
using var cs1 = new MemoryStream();
long cn = FlatChecked.EncodeCheckedArray(Enumerable.Range(0, 500).Select(i => new Row(i, $"r-{i}", true)), cs1);
Check("checked encode count", cn == 500);
cs1.Position = 0;
var cout = FlatChecked.DecodeCheckedArray<Row>(cs1).ToList();
Check("checked clean completion", cout.Count == 500 && cout[499]!.Id == 499);

// Producer error mid-stream: trailer is complete:false, decode throws CheckedStreamException.
IEnumerable<int> Boom()
{
    yield return 1; yield return 2;
    throw new InvalidOperationException("boom at 3");
}
using var cs2 = new MemoryStream();
bool encThrew = false;
try { FlatChecked.EncodeCheckedArray(Boom(), cs2); } catch (InvalidOperationException) { encThrew = true; }
Check("checked encode re-throws producer error", encThrew);
cs2.Position = 0;
var partial = new List<int>();
bool sawStreamError = false;
try { foreach (var v in FlatChecked.DecodeCheckedArray<int>(cs2)) partial.Add(v); }
catch (CheckedStreamException e) { sawStreamError = e.Message.Contains("boom"); }
Check("checked decode surfaces producer error after N items", partial.SequenceEqual(new[] { 1, 2 }) && sawStreamError);

// Truncation: drop the trailer, decode must throw TruncatedStreamException.
using var cs3 = new MemoryStream();
FlatChecked.EncodeCheckedArray(new[] { 1, 2, 3, 4 }, cs3);
var full = cs3.ToArray();
const string terminal = "],\"complete\":true}";
var cut = full[..(full.Length - terminal.Length)]; // lose the whole terminal status
using var cs3b = new MemoryStream(cut);
bool sawTrunc = false;
try { foreach (var _ in FlatChecked.DecodeCheckedArray<int>(cs3b)) { } }
catch (TruncatedStreamException) { sawTrunc = true; }
Check("checked decode detects truncation", sawTrunc);

// Cross-language interop: decode a checked stream written in the reference wire form.
var wire = "{\"items\":[{\"id\":1,\"name\":\"a\"},{\"id\":2,\"name\":\"b\"}],\"complete\":true}";
using var cs4 = new MemoryStream(Encoding.UTF8.GetBytes(wire));
var interop = FlatChecked.DecodeCheckedArray<Row>(cs4).ToList();
Check("checked decodes reference wire envelope", interop.Count == 2 && interop[1]!.Name == "b");

Console.WriteLine(failures == 0 ? "\nALL PASSED" : $"\n{failures} FAILED");
return failures == 0 ? 0 : 1;

record Row(int Id, string Name, bool Ok);

