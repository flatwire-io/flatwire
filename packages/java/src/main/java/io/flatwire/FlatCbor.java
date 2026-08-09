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
 * Streaming CBOR (RFC 8949 binary) format for flatwire, mirroring the Python
 * reference. flatwire's CBOR wire is a stream of concatenated CBOR data items
 * (not a length-prefixed array), so encoding needs no upfront count and decoding
 * reads one item at a time. The encoding is deterministic (shortest heads, map
 * keys sorted by UTF-8 bytes, 64-bit floats), so output is byte-identical across
 * all six flatwire languages. Covers the JSON data model
 * (null/bool/int/float/str/array/map); no tags.
 *
 * <p>Values decode to generic {@code Object} graphs: object -&gt;
 * {@code Map<String,Object>}, array -&gt; {@code List<Object>}, scalars -&gt;
 * Long/Double/Boolean/String/null.
 */
public final class FlatCbor {

    private FlatCbor() {
    }

    public static long encodeArray(Iterable<?> items, OutputStream out) throws IOException {
        long count = 0;
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

    private static void writeHead(DataOutputStream o, int major, long n) throws IOException {
        int mt = major << 5;
        if (n < 24) {
            o.writeByte(mt | (int) n);
        } else if (n <= 0xffL) {
            o.writeByte(mt | 24);
            o.writeByte((int) n);
        } else if (n <= 0xffffL) {
            o.writeByte(mt | 25);
            o.writeShort((int) n);
        } else if (n <= 0xffffffffL) {
            o.writeByte(mt | 26);
            o.writeInt((int) n);
        } else {
            o.writeByte(mt | 27);
            o.writeLong(n);
        }
    }

    @SuppressWarnings("unchecked")
    private static void writeValue(DataOutputStream o, Object v) throws IOException {
        if (v == null) {
            o.writeByte(0xf6);
        } else if (v instanceof Boolean) {
            o.writeByte(((Boolean) v) ? 0xf5 : 0xf4);
        } else if (v instanceof String) {
            byte[] body = ((String) v).getBytes(StandardCharsets.UTF_8);
            writeHead(o, 3, body.length);
            o.write(body);
        } else if (v instanceof Float) {
            writeF64(o, (Float) v);
        } else if (v instanceof Double) {
            writeF64(o, (Double) v);
        } else if (v instanceof Byte || v instanceof Short || v instanceof Integer || v instanceof Long) {
            writeInt(o, ((Number) v).longValue());
        } else if (v instanceof Map) {
            Map<String, Object> map = (Map<String, Object>) v;
            writeHead(o, 5, map.size());
            // Deterministic: sort keys by their UTF-8 byte sequence.
            List<String> keys = new ArrayList<>(map.keySet());
            keys.sort((a, b) -> compareUtf8(a, b));
            for (String k : keys) {
                byte[] kb = k.getBytes(StandardCharsets.UTF_8);
                writeHead(o, 3, kb.length);
                o.write(kb);
                writeValue(o, map.get(k));
            }
        } else if (v instanceof Iterable) {
            List<Object> list = new ArrayList<>();
            for (Object e : (Iterable<Object>) v) list.add(e);
            writeHead(o, 4, list.size());
            for (Object e : list) writeValue(o, e);
        } else {
            throw new IllegalArgumentException("flatwire cbor: unsupported type " + v.getClass().getName());
        }
    }

    private static int compareUtf8(String a, String b) {
        byte[] ba = a.getBytes(StandardCharsets.UTF_8);
        byte[] bb = b.getBytes(StandardCharsets.UTF_8);
        int n = Math.min(ba.length, bb.length);
        for (int i = 0; i < n; i++) {
            int d = (ba[i] & 0xff) - (bb[i] & 0xff);
            if (d != 0) return d;
        }
        return ba.length - bb.length;
    }

    private static void writeF64(DataOutputStream o, double d) throws IOException {
        o.writeByte(0xfb);
        o.writeLong(Double.doubleToLongBits(d));
    }

    private static void writeInt(DataOutputStream o, long v) throws IOException {
        if (v >= 0) {
            writeHead(o, 0, v);
        } else {
            writeHead(o, 1, -1 - v);
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
        if (b < 0) throw new IOException("flatwire cbor: truncated value");
        return b;
    }

    private static byte[] readN(InputStream in, int n) throws IOException {
        byte[] b = new byte[n];
        int off = 0;
        while (off < n) {
            int r = in.read(b, off, n - off);
            if (r < 0) throw new IOException("flatwire cbor: truncated value");
            off += r;
        }
        return b;
    }

    private static long be(byte[] b) {
        long v = 0;
        for (byte x : b) v = (v << 8) | (x & 0xff);
        return v;
    }

    private static long argument(InputStream in, int ai) throws IOException {
        if (ai < 24) return ai;
        switch (ai) {
            case 24: return u8(in);
            case 25: return be(readN(in, 2)) & 0xffffL;
            case 26: return be(readN(in, 4)) & 0xffffffffL;
            case 27: return be(readN(in, 8));
            default: throw new IOException("flatwire cbor: unsupported additional info " + ai);
        }
    }

    private static Object readValue(InputStream in) throws IOException {
        int ib = u8(in);
        int major = ib >> 5;
        int ai = ib & 0x1f;
        switch (major) {
            case 0:
                return argument(in, ai);
            case 1:
                return -1L - argument(in, ai);
            case 2:
                throw new IOException("flatwire cbor: byte-string is not part of the JSON value model");
            case 3:
                return new String(readN(in, (int) argument(in, ai)), StandardCharsets.UTF_8);
            case 4: {
                int n = (int) argument(in, ai);
                List<Object> arr = new ArrayList<>(n);
                for (int i = 0; i < n; i++) arr.add(readValue(in));
                return arr;
            }
            case 5: {
                int n = (int) argument(in, ai);
                Map<String, Object> m = new LinkedHashMap<>();
                for (int i = 0; i < n; i++) {
                    Object k = readValue(in);
                    m.put(String.valueOf(k), readValue(in));
                }
                return m;
            }
            case 7:
                switch (ai) {
                    case 20: return false;
                    case 21: return true;
                    case 22: return null;
                    case 23: return null; // undefined -> null
                    case 25: return decodeF16((int) (be(readN(in, 2)) & 0xffff));
                    case 26: return (double) Float.intBitsToFloat((int) be(readN(in, 4)));
                    case 27: return Double.longBitsToDouble(be(readN(in, 8)));
                    default: throw new IOException("flatwire cbor: unsupported simple value " + ai);
                }
            default:
                throw new IOException("flatwire cbor: unsupported major type " + major);
        }
    }

    private static double decodeF16(int h) {
        int sign = (h >> 15) & 0x1;
        int exp = (h >> 10) & 0x1f;
        int frac = h & 0x3ff;
        double val;
        if (exp == 0) {
            val = (frac / 1024.0) * Math.pow(2, -14);
        } else if (exp == 0x1f) {
            val = frac == 0 ? Double.POSITIVE_INFINITY : Double.NaN;
        } else {
            val = (1.0 + frac / 1024.0) * Math.pow(2, exp - 15);
        }
        return sign == 1 ? -val : val;
    }
}
