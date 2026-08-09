using System.Text;
using System.Text.Json;

namespace FlatWire;

/// <summary>
/// Streaming JSON serialization that keeps memory flat and time linear.
/// The array helpers are the point: a large collection is written and read one
/// element at a time, so peak memory is bounded by the largest single element
/// rather than the size of the whole collection.
/// Wire format is plain JSON, byte-compatible with System.Text.Json.
/// </summary>
public static class Flat
{
    private static readonly JsonSerializerOptions Options = new(JsonSerializerDefaults.Web);

    /// <summary>Encode a whole value to UTF-8 JSON bytes.</summary>
    public static byte[] Encode<T>(T value) => JsonSerializer.SerializeToUtf8Bytes(value, Options);

    /// <summary>Decode UTF-8 JSON bytes to a value.</summary>
    public static T? Decode<T>(ReadOnlySpan<byte> data) => JsonSerializer.Deserialize<T>(data, Options);

    /// <summary>Stream a value to a writable stream via a pooled Utf8JsonWriter.</summary>
    public static void EncodeTo<T>(T value, Stream destination)
    {
        using var writer = new Utf8JsonWriter(destination);
        JsonSerializer.Serialize(writer, value, Options);
    }

    /// <summary>Read a whole value from a readable stream.</summary>
    public static T? DecodeFrom<T>(Stream source) => JsonSerializer.Deserialize<T>(source, Options);

    /// <summary>
    /// Stream a large collection as a JSON array, one element at a time. The
    /// Utf8JsonWriter flushes through a fixed internal buffer, so peak memory is
    /// bounded by the largest single element, not the collection length.
    /// Returns the number of elements written.
    /// </summary>
    public static long EncodeArray<T>(IEnumerable<T> items, Stream destination)
    {
        using var writer = new Utf8JsonWriter(destination);
        writer.WriteStartArray();
        long count = 0;
        foreach (var item in items)
        {
            JsonSerializer.Serialize(writer, item, Options);
            count++;
            // Flush periodically so the writer's buffer never grows with the array.
            if ((count & 0x3FF) == 0) writer.Flush();
        }
        writer.WriteEndArray();
        writer.Flush();
        return count;
    }

    /// <summary>
    /// Lazily read a top-level JSON array from a stream, yielding one element at
    /// a time. Backed by System.Text.Json's streaming DeserializeAsyncEnumerable,
    /// so the whole array is never held in memory at once.
    /// </summary>
    public static IAsyncEnumerable<T?> DecodeArray<T>(Stream source, CancellationToken ct = default)
        => JsonSerializer.DeserializeAsyncEnumerable<T>(source, Options, ct);
}
