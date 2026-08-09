package io.flatwire;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;

class FlatCborTest {

    private static String hex(Object v) throws IOException {
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        FlatCbor.encodeArray(java.util.Collections.singletonList(v), bos);
        StringBuilder sb = new StringBuilder();
        for (byte b : bos.toByteArray()) sb.append(String.format("%02x", b));
        return sb.toString();
    }

    @Test
    void roundTripsTypesAndUnicode() throws IOException {
        Map<String, Object> obj = new LinkedHashMap<>();
        obj.put("id", 1L);
        obj.put("name", "row-1");
        obj.put("ok", true);
        obj.put("tags", Arrays.asList("a", "b"));
        obj.put("note", null);
        List<Object> items = Arrays.asList(
                obj, 42L, -7L, 300L, -300L, 100000L, 3.14159, -1.5, true, false, null,
                "unïcode ✓ €uro 🎯", Arrays.asList(1L, Arrays.asList(2L, 3L)));

        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        long n = FlatCbor.encodeArray(items, bos);
        assertEquals(items.size(), n);

        List<Object> out = new ArrayList<>();
        FlatCbor.decodeArray(new ByteArrayInputStream(bos.toByteArray()), out::add);
        assertEquals(items, out);
    }

    @Test
    void canonicalKnownVectors() throws IOException {
        // Deterministic CBOR bytes shared by every flatwire language.
        assertEquals("00", hex(0L));
        assertEquals("17", hex(23L));
        assertEquals("1818", hex(24L));
        assertEquals("18ff", hex(255L));
        assertEquals("190100", hex(256L));
        assertEquals("20", hex(-1L));
        assertEquals("37", hex(-24L));
        assertEquals("3818", hex(-25L));
        assertEquals("f5", hex(true));
        assertEquals("f4", hex(false));
        assertEquals("f6", hex((Object) null));
        assertEquals("6161", hex("a"));
        assertEquals("83010203", hex(Arrays.asList(1L, 2L, 3L)));
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("b", 2L);
        m.put("a", 1L);
        assertEquals("a2616101616202", hex(m));
        assertEquals("fb3ff8000000000000", hex(1.5));
    }

    @Test
    void moreCompactThanJson() throws IOException {
        List<Object> items = new ArrayList<>();
        for (int i = 0; i < 1000; i++) {
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("id", (long) i);
            row.put("name", "row-" + i);
            row.put("ok", i % 2 == 0);
            items.add(row);
        }
        ByteArrayOutputStream jb = new ByteArrayOutputStream();
        FlatWire.encodeArray(items, jb);
        ByteArrayOutputStream cb = new ByteArrayOutputStream();
        FlatCbor.encodeArray(items, cb);
        assertTrue(cb.size() < jb.size());
    }
}
