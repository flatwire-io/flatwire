using System.Buffers.Binary;
using System.Text;

namespace FlatWire;

/// <summary>
/// Streaming MessagePack (binary) format for flatwire, mirroring the Python
/// reference. flatwire's binary wire is a stream of concatenated MessagePack
/// values (not a length-prefixed array), so encoding needs no upfront count and
/// decoding reads one value at a time. Wire-compatible with standard MessagePack
/// for the JSON data model (null/bool/int/float/str/bin/array/map); no ext types.
///
/// Values decode to object graphs: object -&gt; Dictionary&lt;string,object?&gt;,
/// array -&gt; List&lt;object?&gt;, scalars -&gt; long/double/bool/string/byte[]/null.
/// </summary>
public static class FlatMsgPack
{
    public static long EncodeArray(IEnumerable<object?> items, Stream destination)
    {
        long count = 0;
        var buf = new ArrayBufferWriterLite();
        foreach (var item in items)
        {
            buf.Reset();
            WriteValue(buf, item);
            destination.Write(buf.Span);
            count++;
        }
        destination.Flush();
        return count;
    }

    public static IEnumerable<object?> DecodeArray(Stream source, int chunkSize = 65536)
    {
        var r = new Reader(source, chunkSize);
        while (!r.AtEnd())
            yield return r.ReadValue();
    }

    // --- encoding ---------------------------------------------------------

    private static void WriteValue(ArrayBufferWriterLite w, object? v)
    {
        switch (v)
        {
            case null: w.WriteByte(0xc0); break;
            case bool b: w.WriteByte(b ? (byte)0xc3 : (byte)0xc2); break;
            case string s: WriteStr(w, s); break;
            case byte[] bin: WriteBin(w, bin); break;
            case float f: w.WriteByte(0xca); w.WriteFloatBE(f); break;
            case double d: w.WriteByte(0xcb); w.WriteDoubleBE(d); break;
            case sbyte or short or int or long or byte or ushort or uint or ulong:
                WriteInt(w, Convert.ToInt64(v)); break;
            case IDictionary<string, object?> map: WriteMap(w, map); break;
            case System.Collections.IEnumerable en: WriteArray(w, en); break;
            default: throw new NotSupportedException($"flatwire msgpack: unsupported type {v.GetType().Name}");
        }
    }

    private static void WriteInt(ArrayBufferWriterLite w, long v)
    {
        if (v >= 0 && v <= 0x7f) { w.WriteByte((byte)v); }
        else if (v < 0 && v >= -32) { w.WriteByte((byte)(v & 0xff)); }
        else if (v >= -0x80 && v <= 0x7f) { w.WriteByte(0xd0); w.WriteByte((byte)(sbyte)v); }
        else if (v >= 0 && v <= 0xff) { w.WriteByte(0xcc); w.WriteByte((byte)v); }
        else if (v >= -0x8000 && v <= 0x7fff) { w.WriteByte(0xd1); w.WriteI16BE((short)v); }
        else if (v >= 0 && v <= 0xffff) { w.WriteByte(0xcd); w.WriteU16BE((ushort)v); }
        else if (v >= -0x80000000L && v <= 0x7fffffff) { w.WriteByte(0xd2); w.WriteI32BE((int)v); }
        else if (v >= 0 && v <= 0xffffffffL) { w.WriteByte(0xce); w.WriteU32BE((uint)v); }
        else { w.WriteByte(0xd3); w.WriteI64BE(v); }
    }

    private static void WriteStr(ArrayBufferWriterLite w, string s)
    {
        var body = Encoding.UTF8.GetBytes(s);
        int n = body.Length;
        if (n <= 31) w.WriteByte((byte)(0xa0 | n));
        else if (n <= 0xff) { w.WriteByte(0xd9); w.WriteByte((byte)n); }
        else if (n <= 0xffff) { w.WriteByte(0xda); w.WriteU16BE((ushort)n); }
        else { w.WriteByte(0xdb); w.WriteU32BE((uint)n); }
        w.Write(body);
    }

    private static void WriteBin(ArrayBufferWriterLite w, byte[] body)
    {
        int n = body.Length;
        if (n <= 0xff) { w.WriteByte(0xc4); w.WriteByte((byte)n); }
        else if (n <= 0xffff) { w.WriteByte(0xc5); w.WriteU16BE((ushort)n); }
        else { w.WriteByte(0xc6); w.WriteU32BE((uint)n); }
        w.Write(body);
    }

    private static void WriteArray(ArrayBufferWriterLite w, System.Collections.IEnumerable en)
    {
        var list = new List<object?>();
        foreach (var e in en) list.Add(e);
        int n = list.Count;
        if (n <= 15) w.WriteByte((byte)(0x90 | n));
        else if (n <= 0xffff) { w.WriteByte(0xdc); w.WriteU16BE((ushort)n); }
        else { w.WriteByte(0xdd); w.WriteU32BE((uint)n); }
        foreach (var e in list) WriteValue(w, e);
    }

    private static void WriteMap(ArrayBufferWriterLite w, IDictionary<string, object?> map)
    {
        int n = map.Count;
        if (n <= 15) w.WriteByte((byte)(0x80 | n));
        else if (n <= 0xffff) { w.WriteByte(0xde); w.WriteU16BE((ushort)n); }
        else { w.WriteByte(0xdf); w.WriteU32BE((uint)n); }
        foreach (var kv in map) { WriteStr(w, kv.Key); WriteValue(w, kv.Value); }
    }

    // --- decoding ---------------------------------------------------------

    private sealed class Reader
    {
        private readonly Stream _s;
        private readonly int _chunk;
        private byte[] _buf = new byte[0];
        private int _pos;
        private int _len;
        private bool _eof;

        public Reader(Stream s, int chunk) { _s = s; _chunk = Math.Max(4096, chunk); }

        private bool Fill(int need)
        {
            while (_len - _pos < need)
            {
                if (_pos > 0)
                {
                    Array.Copy(_buf, _pos, _buf, 0, _len - _pos);
                    _len -= _pos; _pos = 0;
                }
                if (_len == _buf.Length)
                {
                    int grow = Math.Max(_buf.Length * 2, _chunk);
                    Array.Resize(ref _buf, grow == 0 ? _chunk : grow);
                }
                int read = _s.Read(_buf, _len, _buf.Length - _len);
                if (read == 0) { _eof = true; return _len - _pos >= need; }
                _len += read;
            }
            return true;
        }

        public bool AtEnd()
        {
            if (_pos < _len) return false;
            if (_eof) return true;
            return !Fill(1);
        }

        private ReadOnlySpan<byte> Take(int n)
        {
            if (!Fill(n)) throw new EndOfStreamException("flatwire msgpack: truncated value");
            var span = _buf.AsSpan(_pos, n);
            _pos += n;
            return span;
        }

        private byte U8() => Take(1)[0];

        public object? ReadValue()
        {
            byte c = U8();
            if (c <= 0x7f) return (long)c;
            if (c >= 0xe0) return (long)(sbyte)c;
            if (c >= 0x80 && c <= 0x8f) return ReadMap(c & 0x0f);
            if (c >= 0x90 && c <= 0x9f) return ReadArr(c & 0x0f);
            if (c >= 0xa0 && c <= 0xbf) return Encoding.UTF8.GetString(Take(c & 0x1f));
            switch (c)
            {
                case 0xc0: return null;
                case 0xc2: return false;
                case 0xc3: return true;
                case 0xc4: return Take(U8()).ToArray();
                case 0xc5: return Take(BinaryPrimitives.ReadUInt16BigEndian(Take(2))).ToArray();
                case 0xc6: return Take((int)BinaryPrimitives.ReadUInt32BigEndian(Take(4))).ToArray();
                case 0xca: return (double)BinaryPrimitives.ReadSingleBigEndian(Take(4));
                case 0xcb: return BinaryPrimitives.ReadDoubleBigEndian(Take(8));
                case 0xcc: return (long)U8();
                case 0xcd: return (long)BinaryPrimitives.ReadUInt16BigEndian(Take(2));
                case 0xce: return (long)BinaryPrimitives.ReadUInt32BigEndian(Take(4));
                case 0xcf: return (long)BinaryPrimitives.ReadUInt64BigEndian(Take(8));
                case 0xd0: return (long)(sbyte)U8();
                case 0xd1: return (long)BinaryPrimitives.ReadInt16BigEndian(Take(2));
                case 0xd2: return (long)BinaryPrimitives.ReadInt32BigEndian(Take(4));
                case 0xd3: return BinaryPrimitives.ReadInt64BigEndian(Take(8));
                case 0xd9: return Encoding.UTF8.GetString(Take(U8()));
                case 0xda: return Encoding.UTF8.GetString(Take(BinaryPrimitives.ReadUInt16BigEndian(Take(2))));
                case 0xdb: return Encoding.UTF8.GetString(Take((int)BinaryPrimitives.ReadUInt32BigEndian(Take(4))));
                case 0xdc: return ReadArr(BinaryPrimitives.ReadUInt16BigEndian(Take(2)));
                case 0xdd: return ReadArr((int)BinaryPrimitives.ReadUInt32BigEndian(Take(4)));
                case 0xde: return ReadMap(BinaryPrimitives.ReadUInt16BigEndian(Take(2)));
                case 0xdf: return ReadMap((int)BinaryPrimitives.ReadUInt32BigEndian(Take(4)));
                default: throw new InvalidDataException($"flatwire msgpack: unknown prefix 0x{c:X2}");
            }
        }

        private List<object?> ReadArr(int n)
        {
            var a = new List<object?>(n);
            for (int i = 0; i < n; i++) a.Add(ReadValue());
            return a;
        }

        private Dictionary<string, object?> ReadMap(int n)
        {
            var m = new Dictionary<string, object?>(n);
            for (int i = 0; i < n; i++)
            {
                var k = ReadValue();
                m[Convert.ToString(k) ?? ""] = ReadValue();
            }
            return m;
        }
    }

    // A minimal growable byte buffer to avoid per-element allocations churn.
    private sealed class ArrayBufferWriterLite
    {
        private byte[] _buf = new byte[256];
        private int _len;
        public ReadOnlySpan<byte> Span => _buf.AsSpan(0, _len);
        public void Reset() => _len = 0;
        private void Ensure(int n) { if (_len + n > _buf.Length) Array.Resize(ref _buf, Math.Max(_buf.Length * 2, _len + n)); }
        public void WriteByte(byte b) { Ensure(1); _buf[_len++] = b; }
        public void Write(ReadOnlySpan<byte> s) { Ensure(s.Length); s.CopyTo(_buf.AsSpan(_len)); _len += s.Length; }
        public void WriteU16BE(ushort v) { Ensure(2); BinaryPrimitives.WriteUInt16BigEndian(_buf.AsSpan(_len), v); _len += 2; }
        public void WriteI16BE(short v) { Ensure(2); BinaryPrimitives.WriteInt16BigEndian(_buf.AsSpan(_len), v); _len += 2; }
        public void WriteU32BE(uint v) { Ensure(4); BinaryPrimitives.WriteUInt32BigEndian(_buf.AsSpan(_len), v); _len += 4; }
        public void WriteI32BE(int v) { Ensure(4); BinaryPrimitives.WriteInt32BigEndian(_buf.AsSpan(_len), v); _len += 4; }
        public void WriteI64BE(long v) { Ensure(8); BinaryPrimitives.WriteInt64BigEndian(_buf.AsSpan(_len), v); _len += 8; }
        public void WriteFloatBE(float v) { Ensure(4); BinaryPrimitives.WriteSingleBigEndian(_buf.AsSpan(_len), v); _len += 4; }
        public void WriteDoubleBE(double v) { Ensure(8); BinaryPrimitives.WriteDoubleBigEndian(_buf.AsSpan(_len), v); _len += 8; }
    }
}
