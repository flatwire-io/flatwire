using System.Text;

namespace FlatWire;

/// <summary>
/// HTTP framework adapter for flatwire. The adoption moment isn't
/// <c>EncodeArray(items, stream)</c> — it's returning a streamed, flat-memory
/// response in one line from ASP.NET, with the right Content-Type for you.
///
/// <para>flatwire stays dependency-free (no ASP.NET reference), so the adapter is
/// a small helper over a <see cref="Stream"/> plus a media-type map. It drops
/// straight into a Minimal API via the built-in <c>Results.Stream</c>:</para>
///
/// <code>
/// app.MapGet("/rows", () =>
///     Results.Stream(
///         stream => { FlatHttp.WriteArray(GetRows(), stream, "cbor"); return Task.CompletedTask; },
///         FlatHttp.MediaTypes["cbor"]));
/// </code>
///
/// <para>Or write straight to <c>HttpContext.Response.Body</c> (also a Stream),
/// setting <c>Response.ContentType = FlatHttp.MediaTypes[fmt]</c> first.</para>
/// </summary>
public static class FlatHttp
{
    /// <summary>Maps a flatwire format name to its HTTP Content-Type.</summary>
    public static readonly IReadOnlyDictionary<string, string> MediaTypes =
        new Dictionary<string, string>
        {
            ["json"] = "application/json",
            ["xml"] = "application/xml",
            ["msgpack"] = "application/msgpack",
            ["cbor"] = "application/cbor",
        };

    /// <summary>
    /// Stream <paramref name="items"/> to <paramref name="destination"/> in the
    /// given format (json/xml/msgpack/cbor), one element at a time, so peak memory
    /// stays bounded by the largest single element. Returns the element count.
    /// Set the response Content-Type from <see cref="MediaTypes"/> at the call
    /// site (the helper only touches the byte stream, never a framework type).
    /// </summary>
    public static long WriteArray(IEnumerable<object?> items, Stream destination, string format = "json")
    {
        return format switch
        {
            "json" => Flat.EncodeArray(items, destination),
            "xml" => FlatXml.EncodeArray(items, destination),
            "msgpack" => FlatMsgPack.EncodeArray(items, destination),
            "cbor" => FlatCbor.EncodeArray(items, destination),
            _ => throw new ArgumentException(
                $"unknown format '{format}' (expected json, xml, msgpack, or cbor)", nameof(format)),
        };
    }

    /// <summary>
    /// The typed-generic overload for JSON (the other formats decode to object
    /// graphs, so they use the object? overload above). Streams <typeparamref name="T"/>
    /// elements as a JSON array with flat memory.
    /// </summary>
    public static long WriteJsonArray<T>(IEnumerable<T> items, Stream destination)
        => Flat.EncodeArray(items, destination);
}
