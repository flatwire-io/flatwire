package io.flatwire;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.management.ThreadMXBean;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.lang.management.ManagementFactory;
import java.util.ArrayList;
import java.util.List;

/**
 * Head-to-head Java benchmark: Jackson materialized vs flatwire streaming,
 * measuring per-thread allocated bytes and wall-clock time.
 *
 * <p>Memory is measured with {@code com.sun.management.ThreadMXBean
 * .getThreadAllocatedBytes()} - the JVM's precise per-thread cumulative
 * allocation counter (analogous to Python's tracemalloc / .NET's
 * GetAllocatedBytesForCurrentThread). Streaming keeps allocated bytes far lower
 * than materializing the whole collection.
 *
 * <p>Run (after {@code gradle build}) with the compiled classpath, or via the
 * {@code benchmark} Gradle task added in build.gradle.
 */
public final class Benchmark {

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final ThreadMXBean TMX = (ThreadMXBean) ManagementFactory.getThreadMXBean();

    public record Row(int id, String name, String payload, boolean ok) {
    }

    static List<Row> makeRows(int n) {
        List<Row> list = new ArrayList<>(n);
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < 200; i++) sb.append('x');
        String pay = sb.toString();
        for (int i = 0; i < n; i++) list.add(new Row(i, "row-" + i, pay, i % 2 == 0));
        return list;
    }

    interface Op {
        void run() throws Exception;
    }

    static long allocatedBy(Op op) throws Exception {
        System.gc();
        long before = TMX.getThreadAllocatedBytes(Thread.currentThread().getId());
        op.run();
        long after = TMX.getThreadAllocatedBytes(Thread.currentThread().getId());
        return after - before;
    }

    // Peak LIVE heap during the operation, sampled from a background thread.
    // Cumulative allocation (getThreadAllocatedBytes) counts every per-element
    // object, so streaming decode looks similar to materializing; the flat-memory
    // promise is about peak live heap, which this captures.
    static long peakLiveDuring(Op op) throws Exception {
        Runtime rt = Runtime.getRuntime();
        System.gc();
        long baseline = rt.totalMemory() - rt.freeMemory();
        final long[] peak = {baseline};
        final boolean[] stop = {false};
        Thread sampler = new Thread(() -> {
            while (!stop[0]) {
                long used = rt.totalMemory() - rt.freeMemory();
                if (used > peak[0]) peak[0] = used;
                try {
                    Thread.sleep(0, 200_000);
                } catch (InterruptedException ignored) {
                    return;
                }
            }
        });
        sampler.setDaemon(true);
        sampler.start();
        op.run();
        long end = rt.totalMemory() - rt.freeMemory();
        if (end > peak[0]) peak[0] = end;
        stop[0] = true;
        sampler.join();
        return Math.max(0, peak[0] - baseline);
    }

    static double medianSeconds(Op op, int iters) throws Exception {
        op.run(); // warm up
        double[] samples = new double[iters];
        for (int i = 0; i < iters; i++) {
            long t0 = System.nanoTime();
            op.run();
            samples[i] = (System.nanoTime() - t0) / 1e9;
        }
        java.util.Arrays.sort(samples);
        return samples[samples.length / 2];
    }

    static String human(long n) {
        String[] u = {"B", "KB", "MB", "GB"};
        double v = n;
        int i = 0;
        while (v >= 1024 && i < u.length - 1) {
            v /= 1024;
            i++;
        }
        return i == 0 ? String.format("%.0f%s", v, u[i]) : String.format("%.1f%s", v, u[i]);
    }

    static final class NullOut extends OutputStream {
        @Override
        public void write(int b) {
        }

        @Override
        public void write(byte[] b, int off, int len) {
        }
    }

    public static void main(String[] args) throws Exception {
        System.out.println("Java benchmark: Jackson materialized vs flatwire streaming\n");
        System.out.println("(encode = cumulative allocated bytes; decode = peak live heap)\n");
        System.out.printf("%9s %9s | %12s %12s | %12s %12s%n",
                "elements", "payload", "enc whole", "enc stream", "agg whole", "agg stream");
        System.out.println("-".repeat(78));

        for (int n : new int[]{1000, 10000, 50000}) {
            List<Row> items = makeRows(n);
            byte[] blob = MAPPER.writeValueAsBytes(items);
            int size = blob.length;

            long encWhole = allocatedBy(() -> {
                byte[] b = MAPPER.writeValueAsBytes(items);
                if (b.length < 0) throw new IOException();
            });
            long encStream = allocatedBy(() -> FlatWire.encodeArray(items, new NullOut()));

            // Decode uses peak-live (not cumulative) so the streaming win is visible.
            long aggWhole = peakLiveDuring(() -> {
                Row[] all = MAPPER.readValue(blob, Row[].class);
                long t = 0;
                for (Row r : all) t += r.id();
                if (t < 0) throw new IOException();
            });
            long aggStream = peakLiveDuring(() -> {
                final long[] t = {0};
                FlatWire.decodeArray(new ByteArrayInputStream(blob), Row.class, r -> t[0] += r.id());
                if (t[0] < 0) throw new IOException();
            });

            System.out.printf("%9d %9s | %12s %12s | %12s %12s%n",
                    n, human(size), human(encWhole), human(encStream), human(aggWhole), human(aggStream));

            if (n == 50000) {
                double encWholeT = medianSeconds(() -> {
                    byte[] b = MAPPER.writeValueAsBytes(items);
                    if (b.length < 0) throw new IOException();
                }, 5);
                double encStreamT = medianSeconds(() -> FlatWire.encodeArray(items, new NullOut()), 5);
                double aggWholeT = medianSeconds(() -> {
                    Row[] all = MAPPER.readValue(blob, Row[].class);
                    long t = 0;
                    for (Row r : all) t += r.id();
                    if (t < 0) throw new IOException();
                }, 5);
                double aggStreamT = medianSeconds(() -> {
                    final long[] t = {0};
                    FlatWire.decodeArray(new ByteArrayInputStream(blob), Row.class, r -> t[0] += r.id());
                    if (t[0] < 0) throw new IOException();
                }, 5);
                System.out.printf("%ntime @50k (s): enc_whole=%.4f enc_stream=%.4f agg_whole=%.4f agg_stream=%.4f%n",
                        encWholeT, encStreamT, aggWholeT, aggStreamT);
            }
        }
    }
}
