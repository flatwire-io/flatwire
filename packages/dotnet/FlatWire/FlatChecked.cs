using System.Text;
using System.Text.Json;

namespace FlatWire;

/// <summary>The producer finished a checked stream with <c>complete:false</c>.</summary>
public sealed class CheckedStreamException : Exception
{
    /// <summary>The decoded error payload the producer wrote on the wire.</summary>
    public JsonElement? Error { get; }

    public CheckedStreamException(string message, JsonElement? error = null) : base(message)
    {
        Error = error;
    }
}

/// <summary>The stream ended before a terminal status was written.</summary>
public sealed class TruncatedStreamException : Exception
{
    public TruncatedStreamException(string message) : base(message) { }
}

/// <summary>
/// Partial-stream failure semantics for flatwire (checked streams), matching the
/// Python/Node reference. A streamed collection is wrapped in an envelope whose
/// terminal status is written LAST:
/// <code>
///   {"items":[ e0, e1, ... ],"complete":true}
///   {"items":[ e0, e1, ... ],"complete":false,"error":{"message":"...","type":"..."}}
/// </code>
/// so a consumer can tell clean completion, an in-band producer error after N
/// rows, and truncation apart. The wire is plain JSON, so a checked stream written
/// by any flatwire language decodes here and vice versa. See docs/FAILURE.md.
/// </summary>
public static class FlatChecked
{
    private static readonly JsonSerializerOptions Options = new(JsonSerializerDefaults.Web);

    /// <summary>
    /// Stream <paramref name="items"/> inside a checked envelope, writing the
    /// terminal status last. If iterating the source throws, a
    /// <c>complete:false</c> trailer carrying the error is written before the
    /// original exception is re-thrown, so the consumer can distinguish failure
    /// from truncation. Returns the number of elements written.
    /// </summary>
    public static long EncodeCheckedArray<T>(IEnumerable<T> items, Stream destination)
    {
        destination.Write("{\"items\":["u8);
        long count = 0;
        try
        {
            foreach (var item in items)
            {
                if (count > 0) destination.Write(","u8);
                destination.Write(JsonSerializer.SerializeToUtf8Bytes(item, Options));
                count++;
            }
        }
        catch (Exception ex)
        {
            var err = new Dictionary<string, string>
            {
                ["message"] = ex.Message,
                ["type"] = ex.GetType().Name,
            };
            destination.Write("],\"complete\":false,\"error\":"u8);
            destination.Write(JsonSerializer.SerializeToUtf8Bytes(err, Options));
            destination.Write("}"u8);
            throw;
        }
        destination.Write("],\"complete\":true}"u8);
        return count;
    }

    /// <summary>
    /// Yield each element from a checked envelope, then enforce the terminal
    /// status. Throws <see cref="CheckedStreamException"/> if the producer
    /// signalled <c>complete:false</c>, and <see cref="TruncatedStreamException"/>
    /// if the stream ended before any terminal status. Peak memory stays bounded
    /// by the largest single element plus the small trailer.
    /// </summary>
    public static IEnumerable<T?> DecodeCheckedArray<T>(Stream source)
    {
        using var reader = new StreamReader(source, Encoding.UTF8, false, 65536, leaveOpen: true);
        var chunk = new char[65536];
        var s = new StringBuilder();
        var eof = false;

        bool More()
        {
            if (eof) return false;
            int n = reader.Read(chunk, 0, chunk.Length);
            if (n <= 0) { eof = true; return false; }
            s.Append(chunk, 0, n);
            return true;
        }

        // Consume the fixed header, then drop it so `s` holds only unconsumed
        // items/trailer bytes and stays bounded by the largest element.
        const string header = "{\"items\":[";
        while (s.Length < header.Length)
        {
            if (!More()) throw new TruncatedStreamException("stream ended before items array");
        }
        if (s.ToString(0, header.Length) != header)
            throw new InvalidDataException("DecodeCheckedArray: not a flatwire checked stream");
        s.Remove(0, header.Length);

        int pos = 0, depth = 0;
        bool inString = false, escape = false;

        while (true)
        {
            while (pos < s.Length)
            {
                char ch = s[pos];
                if (inString)
                {
                    if (escape) escape = false;
                    else if (ch == '\\') escape = true;
                    else if (ch == '"') inString = false;
                    pos++;
                    continue;
                }
                if (ch == '"') { inString = true; pos++; }
                else if (ch == '{' || ch == '[') { depth++; pos++; }
                else if (ch == ']' && depth == 0)
                {
                    var seg = s.ToString(0, pos).Trim();
                    if (seg.Length > 0) yield return JsonSerializer.Deserialize<T>(seg, Options);
                    pos++;
                    while (More()) { }
                    var trailer = s.ToString(pos, s.Length - pos).Trim();
                    Finish(trailer);
                    yield break;
                }
                else if (ch == '}' || ch == ']') { depth--; pos++; }
                else if (ch == ',' && depth == 0)
                {
                    var seg = s.ToString(0, pos).Trim();
                    if (seg.Length > 0) yield return JsonSerializer.Deserialize<T>(seg, Options);
                    s.Remove(0, pos + 1);
                    pos = 0;
                }
                else pos++;
            }
            if (!More()) throw new TruncatedStreamException("stream ended inside items array");
        }
    }

    private static void Finish(string trailer)
    {
        if (trailer.Length == 0)
            throw new TruncatedStreamException("stream ended before terminal status");
        using var doc = JsonDocument.Parse("{" + (trailer.StartsWith(',') ? trailer[1..] : trailer));
        var root = doc.RootElement;
        if (!root.TryGetProperty("complete", out var complete))
            throw new TruncatedStreamException("stream ended before terminal status");
        if (complete.ValueKind == JsonValueKind.False)
        {
            var err = root.TryGetProperty("error", out var e) ? e.Clone() : (JsonElement?)null;
            var msg = err is { ValueKind: JsonValueKind.Object } eo &&
                      eo.TryGetProperty("message", out var m) ? m.GetString() : "unknown stream error";
            throw new CheckedStreamException(msg ?? "unknown stream error", err);
        }
    }
}
