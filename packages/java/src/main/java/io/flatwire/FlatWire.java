package io.flatwire;

import com.fasterxml.jackson.core.JsonGenerator;
import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.core.JsonToken;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.function.Consumer;

/**
 * Streaming JSON serialization that keeps memory flat and time linear.
 *
 * <p>The array helpers are the point: a large collection is written and read one
 * element at a time via Jackson's streaming generator/parser, so peak memory is
 * bounded by the largest single element rather than the whole collection. Wire
 * format is plain JSON, compatible with Jackson's ObjectMapper output.
 */
public final class FlatWire {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private FlatWire() {
    }

    /** Encode a whole value to UTF-8 JSON bytes. */
    public static byte[] encode(Object value) throws IOException {
        return MAPPER.writeValueAsBytes(value);
    }

    /** Decode UTF-8 JSON bytes to the given type. */
    public static <T> T decode(byte[] data, Class<T> type) throws IOException {
        return MAPPER.readValue(data, type);
    }

    /** Stream a value straight to an output stream. */
    public static void encodeTo(Object value, OutputStream out) throws IOException {
        MAPPER.writeValue(out, value);
    }

    /** Read a whole value from an input stream. */
    public static <T> T decodeFrom(InputStream in, Class<T> type) throws IOException {
        return MAPPER.readValue(in, type);
    }

    /**
     * Stream a collection as a JSON array, one element at a time. The generator
     * flushes through a fixed buffer, so peak memory is bounded by the largest
     * single element, not the collection length. Returns the element count.
     */
    public static long encodeArray(Iterable<?> items, OutputStream out) throws IOException {
        long count = 0;
        try (JsonGenerator gen = MAPPER.getFactory().createGenerator(out)) {
            gen.writeStartArray();
            for (Object item : items) {
                MAPPER.writeValue(gen, item);
                count++;
                if ((count & 0x3FF) == 0) {
                    gen.flush();
                }
            }
            gen.writeEndArray();
        }
        return count;
    }

    /**
     * Lazily read a top-level JSON array from an input stream, handing each
     * element to {@code consumer} in turn. Backed by Jackson's streaming parser,
     * so the whole array is never held in memory at once.
     */
    public static <T> void decodeArray(InputStream in, Class<T> type, Consumer<T> consumer)
            throws IOException {
        try (JsonParser parser = MAPPER.getFactory().createParser(in)) {
            if (parser.nextToken() != JsonToken.START_ARRAY) {
                throw new IOException("flatwire: decodeArray expects a top-level JSON array");
            }
            while (parser.nextToken() != JsonToken.END_ARRAY) {
                T element = MAPPER.readValue(parser, type);
                consumer.accept(element);
            }
        }
    }
}
