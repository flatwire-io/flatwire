package io.flatwire;

import java.io.ByteArrayOutputStream;
import java.io.DataOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.PushbackInputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.function.Consumer;

/**
 * Streaming MessagePack (binary) format for flatwire, mirroring the Python
 * reference. flatwire's binary wire is a stream of concatenated MessagePack
 * values (not a length-prefixed array), so encoding needs no upfront count and
 * decoding reads one value at a time. Wire-compatible with standard MessagePack
 * for the JSON data model (null/bool/int/float/str/array/map); no ext types.
 *
 * <p>Values decode to generic {@code Object} graphs: object -&gt;
 * {@code Map<String,Object>}, array -&gt; {@code List<Object>}, scalars -&gt;
 * Long/Double/Boolean/String/null.
 */
public final class FlatMsgPack {

    private FlatMsgPack() {
    }

    public static long encodeArray(Iterable<?> items, OutputStream out) throws IOException {
        long count = 0;
        // Encode each element into a small buffer then flush, keeping memory flat.
        ByteArrayOutputStream bos = new ByteArrayOutputStream(256);
        DataOutputStream dos = new DataOutputStream(bos);
        for (Object item : items) {
            bos.reset();
            writeValue(dos, item);
            dos.flush();
            bos.writeTo(out);
            count++;
        }
        out.flush();
        return count;
    }

    @SuppressWarnings("unchecked")
    private static void writeValue(DataOutputStream o, Object v) throws IOException {
        if (v == null) {
            o.writeByte(0xc0);
        } else if (v instanceof Boolean) {
            o.writeByte(((Boolean) v) ? 0xc3 : 0xc2);
        } else if (v instanceof String) {
            writeStr(o, (String) v);
        } else if (v instanceof Float) {
            writeF64(o, (Float) v);
        } else if (v instanceof Double) {
            writeF64(o, (Double) v);
        } else if (v instanceof Byte || v instanceof Short || v instanceof Integer || v instanceof Long) {
            writeInt(o, ((Number) v).longValue());
        } else if (v instanceof Map) {
            Map<String, Object> map = (Map<String, Object>) v;
            writeMapHeader(o, map.size());
            for (Map.Entry<String, Object> e : map.entrySet()) {
                writeStr(o, e.getKey());
                writeValue(o, e.getValue());
            }
        } else if (v instanceof Iterable) {
            List<Object> list = new ArrayList<>();
            for (Object e : (Iterable<Object>) v) list.add(e);
            writeArrayHeader(o, list.size());
            for (Object e : list) writeValue(o, e);
        } else {
            throw new IllegalArgumentException("flatwire msgpack: unsupported type " + v.getClass().getName());
        }
    }

    private static void writeF64(DataOutputStream o, double d) throws IOException {
        o.writeByte(0xcb);
        o.writeLong(Double.doubleToLongBits(d));
    }

    private static void writeInt(DataOutputStream o, long v) throws IOException {
        if (v >= 0 && v <= 0x7f) {
            o.writeByte((int) v);
        } else if (v < 0 && v >= -32) {
            o.writeByte((int) (v & 0xff));
        } else if (v >= -0x80 && v <= 0x7f) {
            o.writeByte(0xd0);
            o.writeByte((int) v);
        } else if (v >= -0x8000 && v <= 0x7fff) {
            o.writeByte(0xd1);
            o.writeShort((int) v);
        } else if (v >= -0x80000000L && v <= 0x7fffffffL) {
            o.writeByte(0xd2);
            o.writeInt((int) v);
        } else {
            o.writeByte(0xd3);
            o.writeLong(v);
        }
    }

    private static void writeStr(DataOutputStream o, String s) throws IOException {
        byte[] body = s.getBytes(StandardCharsets.UTF_8);
        int n = body.length;
        if (n <= 31) {
            o.writeByte(0xa0 | n);
        } else if (n <= 0xff) {
            o.writeByte(0xd9);
            o.writeByte(n);
        } else if (n <= 0xffff) {
            o.writeByte(0xda);
            o.writeShort(n);
        } else {
            o.writeByte(0xdb);
            o.writeInt(n);
        }
        o.write(body);
    }

    private static void writeArrayHeader(DataOutputStream o, int n) throws IOException {
        if (n <= 15) {
            o.writeByte(0x90 | n);
        } else if (n <= 0xffff) {
            o.writeByte(0xdc);
            o.writeShort(n);
        } else {
            o.writeByte(0xdd);
            o.writeInt(n);
        }
    }

    private static void writeMapHeader(DataOutputStream o, int n) throws IOException {
        if (n <= 15) {
            o.writeByte(0x80 | n);
        } else if (n <= 0xffff) {
            o.writeByte(0xde);
            o.writeShort(n);
        } else {
            o.writeByte(0xdf);
            o.writeInt(n);
        }
    }

    // --- decoding ---------------------------------------------------------

    public static void decodeArray(InputStream in, Consumer<Object> consumer) throws IOException {
        PushbackInputStream pb = new PushbackInputStream(new java.io.BufferedInputStream(in, 65536), 1);
        while (true) {
            int peek = pb.read();
            if (peek < 0) return;
            pb.unread(peek);
            consumer.accept(readValue(pb));
        }
    }

    private static int u8(InputStream in) throws IOException {
        int b = in.read();
        if (b < 0) throw new IOException("flatwire msgpack: truncated value");
        return b;
    }

    private static byte[] readN(InputStream in, int n) throws IOException {
        byte[] b = new byte[n];
        int off = 0;
        while (off < n) {
            int r = in.read(b, off, n - off);
            if (r < 0) throw new IOException("flatwire msgpack: truncated value");
            off += r;
        }
        return b;
    }

    private static long be(byte[] b) {
        long v = 0;
        for (byte x : b) v = (v << 8) | (x & 0xff);
        return v;
    }

    private static Object readValue(InputStream in) throws IOException {
        int c = u8(in);
        if (c <= 0x7f) return (long) c;
        if (c >= 0xe0) return (long) (byte) c;
        if (c >= 0x80 && c <= 0x8f) return readMap(in, c & 0x0f);
        if (c >= 0x90 && c <= 0x9f) return readArray(in, c & 0x0f);
        if (c >= 0xa0 && c <= 0xbf) return new String(readN(in, c & 0x1f), StandardCharsets.UTF_8);
        switch (c) {
            case 0xc0: return null;
            case 0xc2: return false;
            case 0xc3: return true;
            case 0xca: return (double) Float.intBitsToFloat((int) be(readN(in, 4)));
            case 0xcb: return Double.longBitsToDouble(be(readN(in, 8)));
            case 0xcc: return (long) u8(in);
            case 0xcd: return be(readN(in, 2)) & 0xffffL;
            case 0xce: return be(readN(in, 4)) & 0xffffffffL;
            case 0xcf: return be(readN(in, 8)); // may be negative if > Long.MAX; acceptable for JSON model
            case 0xd0: return (long) (byte) u8(in);
            case 0xd1: return (long) (short) be(readN(in, 2));
            case 0xd2: return (long) (int) be(readN(in, 4));
            case 0xd3: return be(readN(in, 8));
            case 0xd9: return new String(readN(in, u8(in)), StandardCharsets.UTF_8);
            case 0xda: return new String(readN(in, (int) (be(readN(in, 2)) & 0xffff)), StandardCharsets.UTF_8);
            case 0xdb: return new String(readN(in, (int) (be(readN(in, 4)) & 0xffffffffL)), StandardCharsets.UTF_8);
            case 0xdc: return readArray(in, (int) (be(readN(in, 2)) & 0xffff));
            case 0xdd: return readArray(in, (int) (be(readN(in, 4)) & 0xffffffffL));
            case 0xde: return readMap(in, (int) (be(readN(in, 2)) & 0xffff));
            case 0xdf: return readMap(in, (int) (be(readN(in, 4)) & 0xffffffffL));
            case 0xc4: case 0xc5: case 0xc6:
                throw new IOException("flatwire msgpack: binary (bin) type is not part of the JSON value model");
            default:
                throw new IOException(String.format("flatwire msgpack: unknown prefix 0x%02x", c));
        }
    }

    private static List<Object> readArray(InputStream in, int n) throws IOException {
        List<Object> arr = new ArrayList<>(n);
        for (int i = 0; i < n; i++) arr.add(readValue(in));
        return arr;
    }

    private static Map<String, Object> readMap(InputStream in, int n) throws IOException {
        Map<String, Object> m = new LinkedHashMap<>();
        for (int i = 0; i < n; i++) {
            Object k = readValue(in);
            m.put(String.valueOf(k), readValue(in));
        }
        return m;
    }
}
