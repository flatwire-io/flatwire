package io.flatwire;

import java.io.IOException;
import java.io.OutputStream;
import java.util.Map;

/**
 * HTTP framework adapter for flatwire. The adoption moment isn't
 * {@code encodeArray(items, out)} — it's returning a streamed, flat-memory
 * response in one line from your web stack, with the right Content-Type for you.
 *
 * <p>flatwire stays dependency-free (no Servlet or Spring dependency), so the
 * adapter is a small helper over an {@link OutputStream} plus a media-type map.
 * It drops straight into a Servlet:</p>
 *
 * <pre>
 * protected void doGet(HttpServletRequest req, HttpServletResponse resp) throws IOException {
 *     resp.setContentType(FlatWireHttp.MEDIA_TYPES.get("cbor"));
 *     FlatWireHttp.writeArray(getRows(), resp.getOutputStream(), "cbor");   // flat memory
 * }
 * </pre>
 *
 * <p>or a Spring {@code StreamingResponseBody}:</p>
 *
 * <pre>
 * &#64;GetMapping(value = "/rows", produces = "application/cbor")
 * StreamingResponseBody rows() {
 *     return out -&gt; FlatWireHttp.writeArray(getRows(), out, "cbor");
 * }
 * </pre>
 */
public final class FlatWireHttp {

    private FlatWireHttp() {
    }

    /** Maps a flatwire format name to its HTTP Content-Type. */
    public static final Map<String, String> MEDIA_TYPES = Map.of(
            "json", "application/json",
            "xml", "application/xml",
            "msgpack", "application/msgpack",
            "cbor", "application/cbor");

    /**
     * Stream {@code items} to {@code out} in the given format
     * (json/xml/msgpack/cbor), one element at a time, so peak memory stays bounded
     * by the largest single element. Returns the element count. Set the response
     * Content-Type from {@link #MEDIA_TYPES} at the call site (this helper only
     * touches the byte stream, never a framework type).
     */
    public static long writeArray(Iterable<?> items, OutputStream out, String format) throws IOException {
        switch (format) {
            case "json":
                return FlatWire.encodeArray(items, out);
            case "xml":
                try {
                    return FlatXml.encodeArray(items, out);
                } catch (javax.xml.stream.XMLStreamException e) {
                    throw new IOException("flatwire: XML encoding failed", e);
                }
            case "msgpack":
                return FlatMsgPack.encodeArray(items, out);
            case "cbor":
                return FlatCbor.encodeArray(items, out);
            default:
                throw new IllegalArgumentException(
                        "unknown format '" + format + "' (expected json, xml, msgpack, or cbor)");
        }
    }
}
