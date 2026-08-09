package io.flatwire;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

import org.junit.jupiter.api.Test;

class FlatCheckedTest {

    @Test
    void cleanCompletionYieldsAllItems() throws IOException {
        List<Integer> items = new ArrayList<>();
        for (int i = 0; i < 500; i++) {
            items.add(i);
        }
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        long n = FlatChecked.encodeCheckedArray(items, out);
        assertEquals(500, n);

        List<Integer> got = new ArrayList<>();
        FlatChecked.decodeCheckedArray(
                new ByteArrayInputStream(out.toByteArray()), Integer.class, got::add);
        assertEquals(items, got);
    }

    @Test
    void producerErrorSurfacesAfterNItems() {
        // Reference wire form: two items then an error trailer.
        String wire = "{\"items\":[1,2],\"complete\":false,"
                + "\"error\":{\"message\":\"boom\",\"type\":\"ValueError\"}}";
        List<Integer> got = new ArrayList<>();
        FlatChecked.CheckedStreamException ex = assertThrows(
                FlatChecked.CheckedStreamException.class,
                () -> FlatChecked.decodeCheckedArray(
                        new ByteArrayInputStream(wire.getBytes(StandardCharsets.UTF_8)),
                        Integer.class, got::add));
        assertEquals(Arrays.asList(1, 2), got);
        assertTrue(ex.getMessage().contains("boom"));
        assertEquals("boom", ex.getError().get("message").asText());
    }

    @Test
    void truncationIsDetected() throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        FlatChecked.encodeCheckedArray(Arrays.asList(1, 2, 3, 4), out);
        byte[] full = out.toByteArray();
        String terminal = "],\"complete\":true}";
        // Drop the whole terminal status so the closing ] is never seen.
        byte[] cut = Arrays.copyOf(full, full.length - terminal.getBytes(StandardCharsets.UTF_8).length);

        assertThrows(FlatChecked.TruncatedStreamException.class,
                () -> FlatChecked.decodeCheckedArray(
                        new ByteArrayInputStream(cut), Integer.class, x -> { }));
    }

    @Test
    void decodesReferenceWireEnvelope() throws IOException {
        String wire = "{\"items\":[{\"id\":1,\"name\":\"a\"},{\"id\":2,\"name\":\"b\"}],\"complete\":true}";
        List<java.util.Map<String, Object>> rows = new ArrayList<>();
        @SuppressWarnings("unchecked")
        Class<java.util.Map<String, Object>> mapType =
                (Class<java.util.Map<String, Object>>) (Class<?>) java.util.Map.class;
        FlatChecked.decodeCheckedArray(
                new ByteArrayInputStream(wire.getBytes(StandardCharsets.UTF_8)), mapType, rows::add);
        assertEquals(2, rows.size());
        assertEquals("b", rows.get(1).get("name"));
    }
}
