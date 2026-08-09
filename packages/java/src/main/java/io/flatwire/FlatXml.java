package io.flatwire;

import javax.xml.stream.XMLInputFactory;
import javax.xml.stream.XMLOutputFactory;
import javax.xml.stream.XMLStreamConstants;
import javax.xml.stream.XMLStreamException;
import javax.xml.stream.XMLStreamReader;
import javax.xml.stream.XMLStreamWriter;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.function.Consumer;

/**
 * Streaming XML format for flatwire, mirroring the JSON path and the Python/JS
 * reference. XML has no native types, so flatwire uses an explicit, typed,
 * fully round-trippable convention (see docs/FORMATS.md):
 *
 * <pre>
 *   42        -&gt; &lt;item type="int"&gt;42&lt;/item&gt;
 *   "hi"      -&gt; &lt;item type="str"&gt;hi&lt;/item&gt;
 *   true      -&gt; &lt;item type="bool"&gt;true&lt;/item&gt;
 *   null      -&gt; &lt;item type="null"/&gt;
 *   {"id":1}  -&gt; &lt;item type="object"&gt;&lt;f k="id" type="int"&gt;1&lt;/f&gt;&lt;/item&gt;
 *   [1,2]     -&gt; &lt;item type="array"&gt;&lt;e type="int"&gt;1&lt;/e&gt;&lt;e type="int"&gt;2&lt;/e&gt;&lt;/item&gt;
 * </pre>
 *
 * <p>Values are generic {@code Object} graphs: object -&gt;
 * {@code Map<String,Object>}, array -&gt; {@code List<Object>}, scalars -&gt;
 * Long/Double/Boolean/String/null. Encoding uses a streaming
 * {@link XMLStreamWriter}; decoding uses a streaming {@link XMLStreamReader} that
 * builds one {@code <item>} subtree at a time, so peak memory stays bounded by
 * the largest element.
 */
public final class FlatXml {

    private static final XMLOutputFactory OUT = XMLOutputFactory.newFactory();
    private static final XMLInputFactory IN = XMLInputFactory.newFactory();

    static {
        // Harden the parser against external entity / DTD attacks.
        IN.setProperty(XMLInputFactory.IS_SUPPORTING_EXTERNAL_ENTITIES, Boolean.FALSE);
        IN.setProperty(XMLInputFactory.SUPPORT_DTD, Boolean.FALSE);
    }

    private FlatXml() {
    }

    public static long encodeArray(Iterable<?> items, OutputStream out) throws XMLStreamException {
        return encodeArray(items, out, "items");
    }

    public static long encodeArray(Iterable<?> items, OutputStream out, String root) throws XMLStreamException {
        XMLStreamWriter w = OUT.createXMLStreamWriter(out, "UTF-8");
        long count = 0;
        try {
            w.writeStartDocument("UTF-8", "1.0");
            w.writeStartElement(root);
            for (Object item : items) {
                writeValue(w, "item", null, item);
                count++;
            }
            w.writeEndElement();
            w.writeEndDocument();
        } finally {
            w.flush();
            w.close();
        }
        return count;
    }

    @SuppressWarnings("unchecked")
    private static void writeValue(XMLStreamWriter w, String tag, String key, Object v) throws XMLStreamException {
        String t = typeOf(v);
        w.writeStartElement(tag);
        if (key != null) w.writeAttribute("k", key);
        w.writeAttribute("type", t);
        switch (t) {
            case "null":
                break;
            case "object":
                for (Map.Entry<String, Object> e : ((Map<String, Object>) v).entrySet())
                    writeValue(w, "f", e.getKey(), e.getValue());
                break;
            case "array":
                for (Object e : (List<Object>) v)
                    writeValue(w, "e", null, e);
                break;
            case "bool":
                w.writeCharacters(((Boolean) v) ? "true" : "false");
                break;
            default:
                w.writeCharacters(String.valueOf(v));
                break;
        }
        w.writeEndElement();
    }

    public static void decodeArray(InputStream in, Consumer<Object> consumer) throws XMLStreamException {
        decodeArray(in, "item", consumer);
    }

    public static void decodeArray(InputStream in, String item, Consumer<Object> consumer) throws XMLStreamException {
        XMLStreamReader r = IN.createXMLStreamReader(in, "UTF-8");
        try {
            // Advance to the root start element.
            while (r.hasNext() && r.next() != XMLStreamConstants.START_ELEMENT) {
                // skip prolog
            }
            // Now inside root; iterate its children.
            while (r.hasNext()) {
                int ev = r.next();
                if (ev == XMLStreamConstants.START_ELEMENT && r.getLocalName().equals(item)) {
                    consumer.accept(readValue(r));
                } else if (ev == XMLStreamConstants.END_ELEMENT) {
                    return; // root end
                }
            }
        } finally {
            r.close();
        }
    }

    // Reads the element whose START_ELEMENT the reader is currently on; leaves
    // the reader positioned on that element's END_ELEMENT.
    private static Object readValue(XMLStreamReader r) throws XMLStreamException {
        String t = r.getAttributeValue(null, "type");
        if (t == null) t = "str";
        switch (t) {
            case "null":
                skipToEnd(r);
                return null;
            case "object": {
                Map<String, Object> obj = new LinkedHashMap<>();
                while (r.hasNext()) {
                    int ev = r.next();
                    if (ev == XMLStreamConstants.START_ELEMENT) {
                        String k = r.getAttributeValue(null, "k");
                        obj.put(k, readValue(r));
                    } else if (ev == XMLStreamConstants.END_ELEMENT) {
                        return obj;
                    }
                }
                return obj;
            }
            case "array": {
                List<Object> arr = new ArrayList<>();
                while (r.hasNext()) {
                    int ev = r.next();
                    if (ev == XMLStreamConstants.START_ELEMENT) {
                        arr.add(readValue(r));
                    } else if (ev == XMLStreamConstants.END_ELEMENT) {
                        return arr;
                    }
                }
                return arr;
            }
            default: { // scalar
                StringBuilder text = new StringBuilder();
                while (r.hasNext()) {
                    int ev = r.next();
                    if (ev == XMLStreamConstants.CHARACTERS || ev == XMLStreamConstants.CDATA) {
                        text.append(r.getText());
                    } else if (ev == XMLStreamConstants.END_ELEMENT) {
                        return parseScalar(t, text.toString());
                    }
                }
                return parseScalar(t, text.toString());
            }
        }
    }

    private static void skipToEnd(XMLStreamReader r) throws XMLStreamException {
        int depth = 0;
        while (r.hasNext()) {
            int ev = r.next();
            if (ev == XMLStreamConstants.START_ELEMENT) depth++;
            else if (ev == XMLStreamConstants.END_ELEMENT) {
                if (depth == 0) return;
                depth--;
            }
        }
    }

    private static Object parseScalar(String t, String raw) {
        switch (t) {
            case "int":
                return Long.parseLong(raw.trim());
            case "float":
                return Double.parseDouble(raw.trim());
            case "bool":
                return "true".equals(raw.trim());
            default:
                return raw;
        }
    }

    private static String typeOf(Object v) {
        if (v == null) return "null";
        if (v instanceof Boolean) return "bool";
        if (v instanceof Byte || v instanceof Short || v instanceof Integer || v instanceof Long)
            return "int";
        if (v instanceof Float || v instanceof Double) return "float";
        if (v instanceof CharSequence) return "str";
        if (v instanceof Map) return "object";
        if (v instanceof Iterable) return "array";
        throw new IllegalArgumentException("flatwire xml: unsupported type " + v.getClass().getName());
    }
}
