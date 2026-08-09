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

Console.WriteLine(failures == 0 ? "\nALL PASSED" : $"\n{failures} FAILED");
return failures == 0 ? 0 : 1;

record Row(int Id, string Name, bool Ok);
