using System.Text;
using System.Xml;

namespace FlatWire;

/// <summary>
/// Streaming XML format for flatwire, mirroring the JSON path and the Python
/// reference. XML has no native types, so flatwire uses an explicit, typed,
/// fully round-trippable convention:
///
///   42        -> &lt;item type="int"&gt;42&lt;/item&gt;
///   "hi"      -> &lt;item type="str"&gt;hi&lt;/item&gt;
///   true      -> &lt;item type="bool"&gt;true&lt;/item&gt;
///   null      -> &lt;item type="null" /&gt;
///   {"id":1}  -> &lt;item type="object"&gt;&lt;f k="id" type="int"&gt;1&lt;/f&gt;&lt;/item&gt;
///   [1,2]     -> &lt;item type="array"&gt;&lt;e type="int"&gt;1&lt;/e&gt;&lt;e type="int"&gt;2&lt;/e&gt;&lt;/item&gt;
///
/// Encoding uses a forward-only <see cref="XmlWriter"/>; decoding uses a
/// forward-only streaming <see cref="XmlReader"/> that reads one &lt;item&gt;
/// subtree at a time, so peak memory stays bounded by the largest element.
///
/// Values decode to <see cref="object"/> graphs: object -&gt; Dictionary&lt;string,object?&gt;,
/// array -&gt; List&lt;object?&gt;, scalars -&gt; long/double/bool/string/null.
/// </summary>
public static class FlatXml
{
    public static long EncodeArray(IEnumerable<object?> items, Stream destination, string root = "items")
    {
        var settings = new XmlWriterSettings
        {
            Encoding = new UTF8Encoding(false),
            OmitXmlDeclaration = false,
            CloseOutput = false,
        };
        using var w = XmlWriter.Create(destination, settings);
        w.WriteStartDocument();
        w.WriteStartElement(root);
        long count = 0;
        foreach (var item in items)
        {
            WriteValue(w, "item", null, item);
            count++;
            if ((count & 0x3FF) == 0) w.Flush();
        }
        w.WriteEndElement();
        w.WriteEndDocument();
        w.Flush();
        return count;
    }

    public static IEnumerable<object?> DecodeArray(Stream source, string item = "item")
    {
        var settings = new XmlReaderSettings
        {
            IgnoreWhitespace = true,
            IgnoreComments = true,
            CloseInput = false,
            DtdProcessing = DtdProcessing.Prohibit,
        };
        using var r = XmlReader.Create(source, settings);
        // Advance into the root element.
        r.MoveToContent();
        if (r.NodeType != XmlNodeType.Element)
            throw new InvalidOperationException("flatwire xml: expected a root element");
        if (r.IsEmptyElement) yield break;
        int rootDepth = r.Depth;
        r.Read();
        while (!(r.NodeType == XmlNodeType.EndElement && r.Depth == rootDepth))
        {
            if (r.NodeType == XmlNodeType.Element && r.LocalName == item)
            {
                yield return ReadValue(r);
            }
            else
            {
                r.Read();
            }
        }
    }

    private static void WriteValue(XmlWriter w, string tag, string? key, object? value)
    {
        string t = TypeOf(value);
        w.WriteStartElement(tag);
        if (key != null) w.WriteAttributeString("k", key);
        w.WriteAttributeString("type", t);
        switch (t)
        {
            case "null":
                break;
            case "object":
                foreach (var kv in (IDictionary<string, object?>)value!)
                    WriteValue(w, "f", kv.Key, kv.Value);
                break;
            case "array":
                foreach (var e in (IEnumerable<object?>)value!)
                    WriteValue(w, "e", null, e);
                break;
            case "bool":
                w.WriteString((bool)value! ? "true" : "false");
                break;
            default:
                w.WriteString(Convert.ToString(value, System.Globalization.CultureInfo.InvariantCulture));
                break;
        }
        w.WriteEndElement();
    }

    // Reads the element the reader is currently positioned on and returns the value.
    private static object? ReadValue(XmlReader r)
    {
        string t = r.GetAttribute("type") ?? "str";
        bool empty = r.IsEmptyElement;
        if (t == "null")
        {
            if (!empty) r.Read(); // move past; skip to end
            SkipToEndOfCurrent(r, empty);
            return null;
        }
        if (t == "object")
        {
            var obj = new Dictionary<string, object?>();
            if (empty) { AdvancePastEmpty(r); return obj; }
            int depth = r.Depth;
            r.Read();
            while (!(r.NodeType == XmlNodeType.EndElement && r.Depth == depth))
            {
                if (r.NodeType == XmlNodeType.Element)
                {
                    string k = r.GetAttribute("k") ?? "";
                    obj[k] = ReadValue(r);
                }
                else r.Read();
            }
            r.Read(); // consume EndElement
            return obj;
        }
        if (t == "array")
        {
            var arr = new List<object?>();
            if (empty) { AdvancePastEmpty(r); return arr; }
            int depth = r.Depth;
            r.Read();
            while (!(r.NodeType == XmlNodeType.EndElement && r.Depth == depth))
            {
                if (r.NodeType == XmlNodeType.Element) arr.Add(ReadValue(r));
                else r.Read();
            }
            r.Read();
            return arr;
        }
        // scalar
        if (empty) { AdvancePastEmpty(r); return t == "str" ? "" : ParseScalar(t, ""); }
        string text = r.ReadElementContentAsString(); // reads text and consumes EndElement
        return ParseScalar(t, text);
    }

    private static void AdvancePastEmpty(XmlReader r) => r.Read();

    private static void SkipToEndOfCurrent(XmlReader r, bool wasEmpty)
    {
        if (wasEmpty) { r.Read(); return; }
        // positioned inside; read until matching end
        // (only reached for <x type="null"></x>, uncommon)
        r.Read();
    }

    private static object? ParseScalar(string t, string text) => t switch
    {
        "int" => long.Parse(text, System.Globalization.CultureInfo.InvariantCulture),
        "float" => double.Parse(text, System.Globalization.CultureInfo.InvariantCulture),
        "bool" => text == "true",
        _ => text, // str
    };

    private static string TypeOf(object? v) => v switch
    {
        null => "null",
        bool => "bool",
        sbyte or byte or short or ushort or int or uint or long or ulong => "int",
        float or double or decimal => "float",
        string => "str",
        IDictionary<string, object?> => "object",
        IEnumerable<object?> => "array",
        _ => throw new NotSupportedException($"flatwire xml: unsupported type {v.GetType().Name}"),
    };
}

