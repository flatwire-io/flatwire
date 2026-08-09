package io.flatwire;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
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

class FlatWireHttpTest {

    private static List<Object> items() {
        Map<String, Object> a = new LinkedHashMap<>();
        a.put("id", 1L);
        a.put("name", "a");
        return Arrays.asList(a, 42L, "x");
    }

    @Test
    void writeArrayStreamsEveryFormatWithCount() throws IOException {
        for (String fmt : new String[] {"json", "xml", "msgpack", "cbor"}) {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            long n = FlatWireHttp.writeArray(items(), out, fmt);
            assertEquals(3, n, fmt);
            assertTrue(out.size() > 0, fmt);
        }
    }

    @Test
    void cborBodyRoundTrips() throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        FlatWireHttp.writeArray(items(), out, "cbor");
        List<Object> back = new ArrayList<>();
        FlatCbor.decodeArray(new ByteArrayInputStream(out.toByteArray()), back::add);
        assertEquals(3, back.size());
        assertEquals(42L, back.get(1));
    }

    @Test
    void mediaTypesCoverAllFourFormats() {
        assertEquals("application/json", FlatWireHttp.MEDIA_TYPES.get("json"));
        assertEquals("application/xml", FlatWireHttp.MEDIA_TYPES.get("xml"));
        assertEquals("application/msgpack", FlatWireHttp.MEDIA_TYPES.get("msgpack"));
        assertEquals("application/cbor", FlatWireHttp.MEDIA_TYPES.get("cbor"));
    }

    @Test
    void unknownFormatIsRejected() {
        assertThrows(IllegalArgumentException.class,
                () -> FlatWireHttp.writeArray(items(), new ByteArrayOutputStream(), "protobuf"));
    }
}
