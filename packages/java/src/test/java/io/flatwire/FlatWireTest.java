package io.flatwire;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

import org.junit.jupiter.api.Test;

class FlatWireTest {

    @Test
    void encodeDecodeRoundtrip() throws IOException {
        List<Integer> value = Arrays.asList(1, 2, 3);
        byte[] data = FlatWire.encode(value);
        Integer[] back = FlatWire.decode(data, Integer[].class);
        assertEquals(value, Arrays.asList(back));
    }

    @Test
    void encodeArrayThenDecodeArray() throws IOException {
        List<String> items = new ArrayList<>();
        for (int i = 0; i < 1000; i++) {
            items.add("row-" + i);
        }
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        long n = FlatWire.encodeArray(items, out);
        assertEquals(1000, n);

        // Valid ordinary JSON array.
        String[] whole = FlatWire.decode(out.toByteArray(), String[].class);
        assertEquals(1000, whole.length);
        assertEquals("row-500", whole[500]);

        // Streaming decode yields every element.
        List<String> got = new ArrayList<>();
        FlatWire.decodeArray(new ByteArrayInputStream(out.toByteArray()), String.class, got::add);
        assertEquals(items, got);
    }

    @Test
    void decodeArrayHandlesTrickyStrings() throws IOException {
        List<String> tricky = Arrays.asList("has, comma and ] bracket", "plain", "v,][");
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        FlatWire.encodeArray(tricky, out);
        List<String> got = new ArrayList<>();
        FlatWire.decodeArray(new ByteArrayInputStream(out.toByteArray()), String.class, got::add);
        assertEquals(tricky, got);
    }

    @Test
    void decodeArrayRejectsNonArray() {
        assertThrows(IOException.class, () ->
            FlatWire.decodeArray(
                new ByteArrayInputStream("{\"not\":\"array\"}".getBytes()),
                Object.class,
                x -> { }));
    }
}
