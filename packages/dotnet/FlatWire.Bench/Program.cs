// Head-to-head .NET benchmark: System.Text.Json materialized vs flatwire
// streaming, measuring BOTH allocated bytes and wall-clock time.
//
// Peak/allocated memory uses GC.GetAllocatedBytesForCurrentThread() - .NET's
// precise per-thread cumulative allocation counter (analogous to Python's
// tracemalloc). We report total bytes allocated by the operation, which for a
// streaming path stays flat while a materializing path scales with payload size.
//
// Run:  dotnet run -c Release --project FlatWire.Bench

using System.Diagnostics;
using System.Text.Json;
using FlatWire;

var options = new JsonSerializerOptions(JsonSerializerDefaults.Web);

Console.WriteLine(".NET benchmark: System.Text.Json materialized vs flatwire streaming\n");
Console.WriteLine($"{"elements",9} {"payload",9} | {"enc whole",12} {"enc stream",12} | {"agg whole*",12} {"agg stream*",12}");
Console.WriteLine(new string('-', 78));
Console.WriteLine("(* agg columns are PEAK LIVE managed heap during decode-and-aggregate)");

var results = new List<object>();

foreach (int n in new[] { 1_000, 10_000, 50_000 })
{
    var items = MakeRecords(n);
    byte[] blob = JsonSerializer.SerializeToUtf8Bytes(items, options);
    int size = blob.Length;

    long encWhole = AllocatedBy(() => { _ = JsonSerializer.SerializeToUtf8Bytes(items, options); });
    long encStream = AllocatedBy(() => { using var s = new NullStream(); Flat.EncodeArray(items, s); });

    // Cumulative allocations (GC.GetAllocatedBytesForCurrentThread) count every
    // object ever created, so streaming decode - which still creates N records -
    // looks similar to materializing. The memory PROMISE is about peak LIVE
    // memory, so we also sample managed heap live-set during each decode and
    // report its peak.
    long aggWholeAlloc = AllocatedBy(() =>
    {
        var list = JsonSerializer.Deserialize<List<Row>>(blob, options)!;
        long t = 0; foreach (var r in list) t += r.Id; if (t < 0) throw new Exception();
    });
    long aggStreamAlloc = AllocatedBy(() =>
    {
        long t = 0;
        using var ms = new MemoryStream(blob);
        var e = Flat.DecodeArray<Row>(ms).GetAsyncEnumerator();
        try { while (e.MoveNextAsync().AsTask().GetAwaiter().GetResult()) t += e.Current!.Id; }
        finally { e.DisposeAsync().AsTask().GetAwaiter().GetResult(); }
        if (t < 0) throw new Exception();
    });

    long aggWhole = PeakLiveDuring(() =>
    {
        var list = JsonSerializer.Deserialize<List<Row>>(blob, options)!;
        long t = 0; foreach (var r in list) t += r.Id; if (t < 0) throw new Exception();
    });
    long aggStream = PeakLiveDuring(() =>
    {
        long t = 0;
        using var ms = new MemoryStream(blob);
        var e = Flat.DecodeArray<Row>(ms).GetAsyncEnumerator();
        try { while (e.MoveNextAsync().AsTask().GetAwaiter().GetResult()) t += e.Current!.Id; }
        finally { e.DisposeAsync().AsTask().GetAwaiter().GetResult(); }
        if (t < 0) throw new Exception();
    });

    Console.WriteLine($"{n,9} {Human(size),9} | {Human(encWhole),12} {Human(encStream),12} | {Human(aggWhole),12} {Human(aggStream),12}");

    results.Add(new
    {
        elements = n,
        payload_bytes = size,
        encode_whole_bytes = encWhole,
        encode_stream_bytes = encStream,
        agg_whole_peak_live = aggWhole,
        agg_stream_peak_live = aggStream,
        agg_whole_cumulative_alloc = aggWholeAlloc,
        agg_stream_cumulative_alloc = aggStreamAlloc,
    });

    if (n == 50_000)
    {
        double encWholeT = MedianSeconds(() => { _ = JsonSerializer.SerializeToUtf8Bytes(items, options); });
        double encStreamT = MedianSeconds(() => { using var s = new NullStream(); Flat.EncodeArray(items, s); });
        double aggWholeT = MedianSeconds(() =>
        {
            var list = JsonSerializer.Deserialize<List<Row>>(blob, options)!;
            long t = 0; foreach (var r in list) t += r.Id;
        });
        double aggStreamT = MedianSeconds(() =>
        {
            long t = 0; using var ms = new MemoryStream(blob);
            var e = Flat.DecodeArray<Row>(ms).GetAsyncEnumerator();
            try { while (e.MoveNextAsync().AsTask().GetAwaiter().GetResult()) t += e.Current!.Id; }
            finally { e.DisposeAsync().AsTask().GetAwaiter().GetResult(); }
        });
        Console.WriteLine($"\ntime @50k (s): enc_whole={encWholeT:0.0000} enc_stream={encStreamT:0.0000} agg_whole={aggWholeT:0.0000} agg_stream={aggStreamT:0.0000}");
    }
}

var dir = Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "results");
Directory.CreateDirectory(dir);
File.WriteAllText(Path.Combine(dir, "comparison.json"),
    JsonSerializer.Serialize(new { note = "bytes allocated per operation via GC.GetAllocatedBytesForCurrentThread", results },
        new JsonSerializerOptions { WriteIndented = true }));
Console.WriteLine($"\nWrote results/comparison.json");

static string Human(long n)
{
    string[] u = { "B", "KB", "MB", "GB" };
    double v = n;
    int i = 0;
    while (v >= 1024 && i < u.Length - 1) { v /= 1024; i++; }
    return i == 0 ? $"{v:0}{u[i]}" : $"{v:0.0}{u[i]}";
}

static List<Row> MakeRecords(int n)
{
    var list = new List<Row>(n);
    var pay = new string('x', 200);
    for (int i = 0; i < n; i++) list.Add(new Row(i, $"row-{i}", pay, i % 2 == 0));
    return list;
}

static long AllocatedBy(Action a)
{
    GC.Collect();
    GC.WaitForPendingFinalizers();
    long before = GC.GetAllocatedBytesForCurrentThread();
    a();
    long after = GC.GetAllocatedBytesForCurrentThread();
    return after - before;
}

// Peak LIVE managed heap during the operation, measured by sampling
// GC.GetTotalMemory(false) from a background thread. This reflects the
// flat-memory promise: streaming keeps few objects alive at once, so its peak
// live-set stays far below materializing everything, even though both allocate
// a similar cumulative total.
static long PeakLiveDuring(Action a)
{
    GC.Collect();
    GC.WaitForPendingFinalizers();
    long baseline = GC.GetTotalMemory(true);
    long peak = baseline;
    using var stop = new ManualResetEventSlim(false);
    var sampler = new Thread(() =>
    {
        while (!stop.IsSet)
        {
            long cur = GC.GetTotalMemory(false);
            if (cur > peak) peak = cur;
            Thread.Sleep(1);
        }
    }) { IsBackground = true };
    sampler.Start();
    a();
    long end = GC.GetTotalMemory(false);
    if (end > peak) peak = end;
    stop.Set();
    sampler.Join();
    return Math.Max(0, peak - baseline);
}

static double MedianSeconds(Action a, int iters = 5)
{
    a(); // warm up
    var samples = new List<double>(iters);
    for (int i = 0; i < iters; i++)
    {
        var sw = Stopwatch.StartNew();
        a();
        sw.Stop();
        samples.Add(sw.Elapsed.TotalSeconds);
    }
    samples.Sort();
    return samples[samples.Count / 2];
}

record Row(int Id, string Name, string Payload, bool Ok);

sealed class NullStream : Stream
{
    public override bool CanRead => false;
    public override bool CanSeek => false;
    public override bool CanWrite => true;
    public override long Length => 0;
    public override long Position { get; set; }
    public override void Flush() { }
    public override int Read(byte[] b, int o, int c) => 0;
    public override long Seek(long o, SeekOrigin s) => 0;
    public override void SetLength(long v) { }
    public override void Write(byte[] b, int o, int c) { }
    public override void Write(ReadOnlySpan<byte> b) { }
}
