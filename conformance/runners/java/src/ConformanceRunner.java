import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.flatwire.FlatWire;
import io.flatwire.FlatXml;
import io.flatwire.FlatMsgPack;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** flatwire conformance runner (Java). Writes results/java.json. */
public class ConformanceRunner {

    static final ObjectMapper MAPPER = new ObjectMapper();
    static final String[] FORMATS = {"json", "xml", "msgpack"};

    public static void main(String[] args) throws Exception {
        File dir = new File(System.getProperty("user.dir"));
        while (dir != null && !new File(dir, "corpus.json").exists()) dir = dir.getParentFile();
        if (dir == null) throw new RuntimeException("could not locate corpus.json");
        File root = dir;

        JsonNode corpus = MAPPER.readTree(new File(root, "corpus.json"));
        Map<String, Object> cases = new LinkedHashMap<>();
        int passed = 0, total = 0;

        for (JsonNode caseNode : corpus.get("cases")) {
            String name = caseNode.get("name").asText();
            String tier = caseNode.get("tier").asText();
            List<Object> elements = new ArrayList<>();
            for (JsonNode e : caseNode.get("elements")) elements.add(toModel(e));

            Map<String, Object> fmtResults = new LinkedHashMap<>();
            for (String fmt : FORMATS) {
                total++;
                try {
                    byte[] data = encode(elements, fmt);
                    List<Object> out = decode(data, fmt);
                    boolean rt = modelEquals(elements, out);
                    if (rt) passed++;
                    Map<String, Object> r = new LinkedHashMap<>();
                    r.put("roundtrip", rt);
                    r.put("sha256", sha256(data));
                    r.put("bytes", data.length);
                    fmtResults.put(fmt, r);
                } catch (Exception ex) {
                    Map<String, Object> r = new LinkedHashMap<>();
                    r.put("roundtrip", false);
                    r.put("error", ex.getMessage());
                    fmtResults.put(fmt, r);
                }
            }
            Map<String, Object> c = new LinkedHashMap<>();
            c.put("tier", tier);
            c.put("formats", fmtResults);
            cases.put(name, c);
        }

        Map<String, Object> results = new LinkedHashMap<>();
        results.put("lang", "java");
        results.put("tested_locally", true);
        results.put("cases", cases);

        File outFile = new File(new File(root, "results"), "java.json");
        outFile.getParentFile().mkdirs();
        Files.writeString(outFile.toPath(), MAPPER.writerWithDefaultPrettyPrinter().writeValueAsString(results));
        System.out.printf("java conformance: %d/%d round-trip; wrote %s%n", passed, total, outFile);
    }

    static Object toModel(JsonNode n) {
        if (n.isNull()) return null;
        if (n.isBoolean()) return n.asBoolean();
        if (n.isIntegralNumber()) return n.asLong();
        if (n.isNumber()) return n.asDouble();
        if (n.isTextual()) return n.asText();
        if (n.isArray()) {
            List<Object> a = new ArrayList<>();
            for (JsonNode e : n) a.add(toModel(e));
            return a;
        }
        if (n.isObject()) {
            Map<String, Object> m = new LinkedHashMap<>();
            n.fields().forEachRemaining(e -> m.put(e.getKey(), toModel(e.getValue())));
            return m;
        }
        return null;
    }

    static byte[] encode(List<Object> elements, String fmt) throws Exception {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        switch (fmt) {
            case "json": FlatWire.encodeArray(elements, out); break;
            case "xml": FlatXml.encodeArray(elements, out); break;
            case "msgpack": FlatMsgPack.encodeArray(elements, out); break;
        }
        return out.toByteArray();
    }

    @SuppressWarnings("unchecked")
    static List<Object> decode(byte[] data, String fmt) throws Exception {
        List<Object> out = new ArrayList<>();
        switch (fmt) {
            case "json":
                // flatwire JSON decodeArray needs a target type; decode each element as Object.
                FlatWire.decodeArray(new ByteArrayInputStream(data), Object.class, o -> out.add(normalizeJackson(o)));
                break;
            case "xml":
                FlatXml.decodeArray(new ByteArrayInputStream(data), out::add);
                break;
            case "msgpack":
                FlatMsgPack.decodeArray(new ByteArrayInputStream(data), out::add);
                break;
        }
        return out;
    }

    // FlatWire JSON decode yields Jackson-mapped Objects (LinkedHashMap/ArrayList/
    // Integer/Long/Double/Boolean/String); normalize numbers to Long/Double.
    @SuppressWarnings("unchecked")
    static Object normalizeJackson(Object o) {
        if (o instanceof Integer) return ((Integer) o).longValue();
        if (o instanceof Long) return o;
        if (o instanceof Number) return ((Number) o).doubleValue();
        if (o instanceof Map) {
            Map<String, Object> m = new LinkedHashMap<>();
            ((Map<String, Object>) o).forEach((k, v) -> m.put(k, normalizeJackson(v)));
            return m;
        }
        if (o instanceof List) {
            List<Object> a = new ArrayList<>();
            for (Object e : (List<Object>) o) a.add(normalizeJackson(e));
            return a;
        }
        return o;
    }

    @SuppressWarnings("unchecked")
    static boolean modelEquals(Object a, Object b) {
        if (a == null || b == null) return a == null && b == null;
        if (a instanceof Number && b instanceof Number) {
            return ((Number) a).doubleValue() == ((Number) b).doubleValue();
        }
        if (a instanceof Map && b instanceof Map) {
            Map<String, Object> ma = (Map<String, Object>) a, mb = (Map<String, Object>) b;
            if (ma.size() != mb.size()) return false;
            for (Map.Entry<String, Object> e : ma.entrySet()) {
                if (!mb.containsKey(e.getKey()) || !modelEquals(e.getValue(), mb.get(e.getKey()))) return false;
            }
            return true;
        }
        if (a instanceof List && b instanceof List) {
            List<Object> la = (List<Object>) a, lb = (List<Object>) b;
            if (la.size() != lb.size()) return false;
            for (int i = 0; i < la.size(); i++) if (!modelEquals(la.get(i), lb.get(i))) return false;
            return true;
        }
        return a.equals(b);
    }

    static String sha256(byte[] data) throws Exception {
        byte[] h = MessageDigest.getInstance("SHA-256").digest(data);
        StringBuilder sb = new StringBuilder();
        for (byte x : h) sb.append(String.format("%02x", x));
        return sb.toString();
    }
}
