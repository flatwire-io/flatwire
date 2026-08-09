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

Console.WriteLine(failures == 0 ? "\nALL PASSED" : $"\n{failures} FAILED");
return failures == 0 ? 0 : 1;

record Row(int Id, string Name, bool Ok);
