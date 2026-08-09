package io.flatwire;

import com.fasterxml.jackson.core.JsonGenerator;
import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.core.JsonToken;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.function.Consumer;

/**
 * Partial-stream failure semantics for flatwire (checked streams), matching the
 * Python/Node reference. A streamed collection is wrapped in an envelope whose
 * terminal status is written LAST:
 *
 * <pre>
 *   {"items":[ e0, e1, ... ],"complete":true}
 *   {"items":[ e0, e1, ... ],"complete":false,"error":{"message":"...","type":"..."}}
 * </pre>
 *
 * so a consumer can tell clean completion, an in-band producer error after N
 * rows, and truncation apart. The wire is plain JSON, so a checked stream
 * written by any flatwire language decodes here and vice versa. See
 * docs/FAILURE.md.
 */
public final class FlatChecked {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private FlatChecked() {
    }

    /** The producer finished a checked stream with {@code complete:false}. */
    public static final class CheckedStreamException extends IOException {
        private final transient JsonNode error;

        public CheckedStreamException(String message, JsonNode error) {
            super(message);
            this.error = error;
        }

        /** The decoded error payload the producer wrote on the wire (may be null). */
        public JsonNode getError() {
            return error;
        }
    }

    /** The stream ended before a terminal status was written. */
    public static final class TruncatedStreamException extends IOException {
        public TruncatedStreamException(String message) {
            super(message);
        }
    }

    /**
     * Stream {@code items} inside a checked envelope, writing the terminal status
     * last. If serializing an element throws, a {@code complete:false} trailer
     * carrying the error is written before the original exception is re-thrown, so
     * the consumer can distinguish failure from truncation. Returns the element
     * count.
     */
    public static long encodeCheckedArray(Iterable<?> items, OutputStream out) throws IOException {
        out.write("{\"items\":[".getBytes(java.nio.charset.StandardCharsets.UTF_8));
        long count = 0;
        try {
            for (Object item : items) {
                if (count > 0) {
                    out.write(',');
                }
                out.write(MAPPER.writeValueAsBytes(item));
                count++;
            }
        } catch (RuntimeException | IOException ex) {
            java.util.Map<String, String> err = new java.util.LinkedHashMap<>();
            err.put("message", ex.getMessage() == null ? ex.toString() : ex.getMessage());
            err.put("type", ex.getClass().getSimpleName());
            out.write("],\"complete\":false,\"error\":".getBytes(java.nio.charset.StandardCharsets.UTF_8));
            out.write(MAPPER.writeValueAsBytes(err));
            out.write('}');
            throw ex;
        }
        out.write("],\"complete\":true}".getBytes(java.nio.charset.StandardCharsets.UTF_8));
        return count;
    }

    /**
     * Lazily read a checked envelope from {@code in}, handing each element to
     * {@code consumer} in turn (one at a time, so peak memory stays flat), then
     * enforce the terminal status. Backed by Jackson's streaming parser.
     *
     * @throws CheckedStreamException if the producer signalled {@code complete:false}
     * @throws TruncatedStreamException if the stream ended before a terminal status
     */
    public static <T> void decodeCheckedArray(InputStream in, Class<T> type, Consumer<T> consumer)
            throws IOException {
        try (JsonParser parser = MAPPER.getFactory().createParser(in)) {
            if (expect(parser) != JsonToken.START_OBJECT) {
                throw new IOException("flatwire: decodeCheckedArray expects a checked stream object");
            }
            if (expect(parser) != JsonToken.FIELD_NAME || !"items".equals(parser.currentName())) {
                throw new IOException("flatwire: checked stream must start with an \"items\" array");
            }
            if (expect(parser) != JsonToken.START_ARRAY) {
                throw new IOException("flatwire: checked stream \"items\" must be an array");
            }

            while (true) {
                JsonToken tok = next(parser);
                if (tok == null) {
                    throw new TruncatedStreamException("stream ended inside items array");
                }
                if (tok == JsonToken.END_ARRAY) {
                    break;
                }
                T element = MAPPER.readValue(parser, type);
                consumer.accept(element);
            }

            boolean seenComplete = false;
            boolean complete = false;
            JsonNode error = null;
            while (true) {
                JsonToken tok = next(parser);
                if (tok == null) {
                    throw new TruncatedStreamException("stream ended before terminal status");
                }
                if (tok == JsonToken.END_OBJECT) {
                    break;
                }
                if (tok == JsonToken.FIELD_NAME) {
                    String field = parser.currentName();
                    next(parser);
                    if ("complete".equals(field)) {
                        complete = parser.getBooleanValue();
                        seenComplete = true;
                    } else if ("error".equals(field)) {
                        error = MAPPER.readTree(parser);
                    } else {
                        parser.skipChildren();
                    }
                }
            }

            if (!seenComplete) {
                throw new TruncatedStreamException("stream ended before terminal status");
            }
            if (!complete) {
                String msg = error != null && error.has("message")
                        ? error.get("message").asText()
                        : "unknown stream error";
                throw new CheckedStreamException(msg, error);
            }
        }
    }

    private static JsonToken expect(JsonParser parser) throws IOException {
        JsonToken tok;
        try {
            tok = parser.nextToken();
        } catch (com.fasterxml.jackson.core.io.JsonEOFException eof) {
            throw new TruncatedStreamException("stream ended before items array");
        }
        if (tok == null) {
            throw new TruncatedStreamException("stream ended before items array");
        }
        return tok;
    }

    private static JsonToken next(JsonParser parser) throws IOException {
        try {
            return parser.nextToken();
        } catch (com.fasterxml.jackson.core.io.JsonEOFException eof) {
            return null;
        }
    }
}
