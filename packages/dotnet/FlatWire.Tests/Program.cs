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

Console.WriteLine(failures == 0 ? "\nALL PASSED" : $"\n{failures} FAILED");
return failures == 0 ? 0 : 1;

record Row(int Id, string Name, bool Ok);

