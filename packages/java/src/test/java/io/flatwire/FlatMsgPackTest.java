package io.flatwire;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;

class FlatMsgPackTest {

    @Test
    void msgpackRoundTripsWithTypes() throws IOException {
        Map<String, Object> obj = new LinkedHashMap<>();
        obj.put("id", 1L);
        obj.put("name", "row-1");
        obj.put("ok", true);
        obj.put("tags", Arrays.asList("a", "b"));
        obj.put("score", 3.5);
        obj.put("note", null);

        List<Object> items = Arrays.asList(
            obj, 42L, -7L, 300L, -300L, 100000L,
            "unïcode ✓ €uro 🎯", Arrays.asList(1L, 2L, 3L), null, true, 3.14159, -1.5);

        ByteArrayOutputStream out = new ByteArrayOutputStream();
        long n = FlatMsgPack.encodeArray(items, out);
        assertEquals(items.size(), n);

        List<Object> got = new ArrayList<>();
        FlatMsgPack.decodeArray(new ByteArrayInputStream(out.toByteArray()), got::add);
        assertEquals(items, got);
    }

    @Test
    void msgpackMoreCompactThanJson() throws IOException {
        List<Object> items = new ArrayList<>();
        for (int i = 0; i < 1000; i++) {
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("id", (long) i);
            row.put("name", "row");
            row.put("ok", i % 2 == 0);
            items.add(row);
        }
        ByteArrayOutputStream mp = new ByteArrayOutputStream();
        FlatMsgPack.encodeArray(items, mp);
        ByteArrayOutputStream js = new ByteArrayOutputStream();
        FlatWire.encodeArray(items, js);
        assertTrue(mp.size() < js.size(), "msgpack " + mp.size() + " vs json " + js.size());
    }

    @Test
    void msgpackStreamsAcrossSmallReads() throws IOException {
        List<Object> items = new ArrayList<>();
        for (int i = 0; i < 2000; i++) {
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("id", (long) i);
            row.put("vals", Arrays.asList((long) i, (long) (i + 1)));
            items.add(row);
        }
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        FlatMsgPack.encodeArray(items, out);
        byte[] data = out.toByteArray();

        InputStream trickle = new InputStream() {
            int pos = 0;

            @Override
            public int read() {
                return pos < data.length ? (data[pos++] & 0xff) : -1;
            }

            @Override
            public int read(byte[] b, int off, int len) {
                if (pos >= data.length) return -1;
                int n = Math.min(5, Math.min(len, data.length - pos));
                System.arraycopy(data, pos, b, off, n);
                pos += n;
                return n;
            }
        };

        List<Object> got = new ArrayList<>();
        FlatMsgPack.decodeArray(trickle, got::add);
        assertEquals(2000, got.size());
        assertEquals(items.get(1000), got.get(1000));
    }
}
