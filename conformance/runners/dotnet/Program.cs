// flatwire conformance runner (.NET). Encodes+decodes every corpus case in every
// format, records round-trip and a SHA-256 of the encoded bytes -> results/dotnet.json.

using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using FlatWire;

string root = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "..", ".."));
string corpusPath = Path.Combine(root, "corpus.json");
if (!File.Exists(corpusPath))
{
    // Fallback: search upward for conformance/corpus.json
    var dir = new DirectoryInfo(AppContext.BaseDirectory);
    while (dir != null && !File.Exists(Path.Combine(dir.FullName, "corpus.json"))) dir = dir.Parent;
    corpusPath = dir != null ? Path.Combine(dir.FullName, "corpus.json") : corpusPath;
    root = Path.GetDirectoryName(corpusPath)!;
}

using var doc = JsonDocument.Parse(File.ReadAllText(corpusPath));
var formats = new[] { "json", "xml", "msgpack", "cbor" };

var cases = new Dictionary<string, object>();
foreach (var caseEl in doc.RootElement.GetProperty("cases").EnumerateArray())
{
    string name = caseEl.GetProperty("name").GetString()!;
    string tier = caseEl.GetProperty("tier").GetString()!;
    var elements = caseEl.GetProperty("elements").EnumerateArray().Select(ToModel).ToList();

    var formatResults = new Dictionary<string, object>();
    foreach (var fmt in formats)
    {
        try
        {
            byte[] data;
            List<object?> outv;
            using (var enc = new MemoryStream())
            {
                switch (fmt)
                {
                    case "json": Flat.EncodeArray(elements, enc); break;
                    case "xml": FlatXml.EncodeArray(elements, enc); break;
                    case "msgpack": FlatMsgPack.EncodeArray(elements, enc); break;
                    case "cbor": FlatCbor.EncodeArray(elements, enc); break;
                }
                data = enc.ToArray();
            }
            using (var dec = new MemoryStream(data))
            {
                outv = fmt switch
                {
                    "json" => DecodeJson(dec),
                    "xml" => FlatXml.DecodeArray(dec).ToList(),
                    "msgpack" => FlatMsgPack.DecodeArray(dec).ToList(),
                    "cbor" => FlatCbor.DecodeArray(dec).ToList(),
                    _ => new List<object?>(),
                };
            }
            bool rt = ModelEquals(elements, outv);
            formatResults[fmt] = new Dictionary<string, object>
            {
                ["roundtrip"] = rt,
                ["sha256"] = Convert.ToHexString(SHA256.HashData(data)).ToLowerInvariant(),
                ["bytes"] = data.Length,
            };
        }
        catch (Exception e)
        {
            formatResults[fmt] = new Dictionary<string, object> { ["roundtrip"] = false, ["error"] = e.Message };
        }
    }
    cases[name] = new Dictionary<string, object> { ["tier"] = tier, ["formats"] = formatResults };
}

var results = new Dictionary<string, object>
{
    ["lang"] = "dotnet",
    ["tested_locally"] = true,
    ["cases"] = cases,
};
string outPath = Path.Combine(root, "results", "dotnet.json");
Directory.CreateDirectory(Path.GetDirectoryName(outPath)!);
File.WriteAllText(outPath, JsonSerializer.Serialize(results, new JsonSerializerOptions { WriteIndented = true }));
int passed = cases.Values.Cast<Dictionary<string, object>>()
    .SelectMany(c => ((Dictionary<string, object>)c["formats"]).Values.Cast<Dictionary<string, object>>())
    .Count(f => f.TryGetValue("roundtrip", out var r) && r is true);
int total = cases.Values.Cast<Dictionary<string, object>>().Sum(c => ((Dictionary<string, object>)c["formats"]).Count);
Console.WriteLine($"dotnet conformance: {passed}/{total} round-trip; wrote {outPath}");

// --- helpers ---

static object? ToModel(JsonElement e) => e.ValueKind switch
{
    JsonValueKind.Null => null,
    JsonValueKind.True => true,
    JsonValueKind.False => false,
    JsonValueKind.String => e.GetString(),
    JsonValueKind.Number => e.TryGetInt64(out var l) ? (object)l : e.GetDouble(),
    JsonValueKind.Array => e.EnumerateArray().Select(ToModel).ToList(),
    JsonValueKind.Object => e.EnumerateObject().ToDictionary(p => p.Name, p => ToModel(p.Value)),
    _ => null,
};

static List<object?> DecodeJson(Stream s)
{
    // Flat.DecodeArray<JsonElement> streams elements; normalize to the model.
    var outv = new List<object?>();
    var e = Flat.DecodeArray<JsonElement>(s).GetAsyncEnumerator();
    try
    {
        while (e.MoveNextAsync().AsTask().GetAwaiter().GetResult())
            outv.Add(ToModel(e.Current));
    }
    finally { e.DisposeAsync().AsTask().GetAwaiter().GetResult(); }
    return outv;
}

static bool ModelEquals(object? a, object? b)
{
    if (a == null || b == null) return a == null && b == null;
    switch (a)
    {
        case IDictionary<string, object?> da when b is IDictionary<string, object?> db:
            if (da.Count != db.Count) return false;
            foreach (var kv in da)
                if (!db.TryGetValue(kv.Key, out var bv) || !ModelEquals(kv.Value, bv)) return false;
            return true;
        case System.Collections.IEnumerable ea when a is not string && b is System.Collections.IEnumerable eb && b is not string:
            var la = ea.Cast<object?>().ToList(); var lb = eb.Cast<object?>().ToList();
            if (la.Count != lb.Count) return false;
            for (int i = 0; i < la.Count; i++) if (!ModelEquals(la[i], lb[i])) return false;
            return true;
        default:
            // Numeric cross-type tolerance: long vs double representing same value.
            if (a is long or double or int && b is long or double or int)
                return Convert.ToDouble(a) == Convert.ToDouble(b);
            return a.Equals(b);
    }
}
