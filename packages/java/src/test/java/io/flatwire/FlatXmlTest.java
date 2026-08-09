package io.flatwire;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import javax.xml.stream.XMLStreamException;

import org.junit.jupiter.api.Test;

class FlatXmlTest {

    @Test
    void xmlRoundTripsWithTypes() throws XMLStreamException {
        Map<String, Object> obj = new LinkedHashMap<>();
        obj.put("id", 1L);
        obj.put("name", "row-1");
        obj.put("ok", true);
        obj.put("tags", Arrays.asList("a", "b"));
        obj.put("score", 3.5);
        obj.put("note", null);

        List<Object> items = Arrays.asList(
            obj,
            42L,
            "has < & > \" chars",
            Arrays.asList(1L, 2L, 3L),
            null,
            true);

        ByteArrayOutputStream out = new ByteArrayOutputStream();
        long n = FlatXml.encodeArray(items, out);
        assertEquals(items.size(), n);

        List<Object> got = new ArrayList<>();
        FlatXml.decodeArray(new ByteArrayInputStream(out.toByteArray()), got::add);
        assertEquals(items, got);
    }

    @Test
    void xmlStreamsAcrossSmallReads() throws XMLStreamException {
        List<Object> items = new ArrayList<>();
        for (int i = 0; i < 1000; i++) {
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("id", (long) i);
            row.put("name", "row-" + i);
            row.put("vals", Arrays.asList((long) i, (long) (i + 1)));
            items.add(row);
        }
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        FlatXml.encodeArray(items, out);

        // Reader that returns a few bytes at a time.
        byte[] data = out.toByteArray();
        InputStream trickle = new InputStream() {
            int pos = 0;
            int calls = 0;

            @Override
            public int read() {
                return pos < data.length ? (data[pos++] & 0xff) : -1;
            }

            @Override
            public int read(byte[] b, int off, int len) {
                if (pos >= data.length) return -1;
                int n = Math.min(7, Math.min(len, data.length - pos));
                System.arraycopy(data, pos, b, off, n);
                pos += n;
                return n;
            }
        };

        List<Object> got = new ArrayList<>();
        FlatXml.decodeArray(trickle, got::add);
        assertEquals(1000, got.size());
        assertEquals(items.get(500), got.get(500));
    }

    @Test
    void xmlCustomRoot() throws XMLStreamException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        Map<String, Object> a = new LinkedHashMap<>();
        a.put("a", 1L);
        FlatXml.encodeArray(Arrays.asList(a), out, "records");
        assertTrue(out.toString().contains("<records>"));
    }
}
