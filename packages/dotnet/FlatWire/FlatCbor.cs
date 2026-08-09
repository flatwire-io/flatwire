using System.Buffers.Binary;
using System.Text;

namespace FlatWire;

/// <summary>
/// Streaming CBOR (RFC 8949 binary) format for flatwire, mirroring the Python
/// reference. flatwire's CBOR wire is a stream of concatenated CBOR data items
/// (not a length-prefixed array), so encoding needs no upfront count and decoding
/// reads one item at a time. The encoding is deterministic (shortest heads,
/// map keys sorted by UTF-8 bytes, 64-bit floats), so output is byte-identical
/// across all six flatwire languages. Covers the JSON data model
/// (null/bool/int/float/str/bytes/array/map); no tags.
///
/// Values decode to object graphs: object -&gt; Dictionary&lt;string,object?&gt;,
/// array -&gt; List&lt;object?&gt;, scalars -&gt; long/double/bool/string/byte[]/null.
/// </summary>
public static class FlatCbor
{
    public static long EncodeArray(IEnumerable<object?> items, Stream destination)
    {
        long count = 0;
        var buf = new BufferLite();
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

    private static void WriteHead(BufferLite w, int major, ulong n)
    {
        byte mt = (byte)(major << 5);
        if (n < 24) { w.WriteByte((byte)(mt | (byte)n)); }
        else if (n <= 0xff) { w.WriteByte((byte)(mt | 24)); w.WriteByte((byte)n); }
        else if (n <= 0xffff) { w.WriteByte((byte)(mt | 25)); w.WriteU16BE((ushort)n); }
        else if (n <= 0xffffffff) { w.WriteByte((byte)(mt | 26)); w.WriteU32BE((uint)n); }
        else { w.WriteByte((byte)(mt | 27)); w.WriteU64BE(n); }
    }

    private static void WriteValue(BufferLite w, object? v)
    {
        switch (v)
        {
            case null: w.WriteByte(0xf6); break;
            case bool b: w.WriteByte(b ? (byte)0xf5 : (byte)0xf4); break;
            case string s:
            {
                var body = Encoding.UTF8.GetBytes(s);
                WriteHead(w, 3, (ulong)body.Length);
                w.Write(body);
                break;
            }
            case byte[] bin:
                WriteHead(w, 2, (ulong)bin.Length);
                w.Write(bin);
                break;
            case float f: w.WriteByte(0xfb); w.WriteDoubleBE(f); break;
            case double d: w.WriteByte(0xfb); w.WriteDoubleBE(d); break;
            case sbyte or short or int or long or byte or ushort or uint or ulong:
                WriteInt(w, Convert.ToInt64(v)); break;
            case IDictionary<string, object?> map: WriteMap(w, map); break;
            case System.Collections.IEnumerable en: WriteArray(w, en); break;
            default: throw new NotSupportedException($"flatwire cbor: unsupported type {v.GetType().Name}");
        }
    }

    private static void WriteInt(BufferLite w, long v)
    {
        if (v >= 0) WriteHead(w, 0, (ulong)v);
        else WriteHead(w, 1, (ulong)(-1 - v));
    }

    private static void WriteArray(BufferLite w, System.Collections.IEnumerable en)
    {
        var list = new List<object?>();
        foreach (var e in en) list.Add(e);
        WriteHead(w, 4, (ulong)list.Count);
        foreach (var e in list) WriteValue(w, e);
    }

    private static void WriteMap(BufferLite w, IDictionary<string, object?> map)
    {
        WriteHead(w, 5, (ulong)map.Count);
        // Deterministic: sort keys by their UTF-8 byte sequence.
        foreach (var key in map.Keys.OrderBy(k => Encoding.UTF8.GetBytes(k), Utf8ByteComparer.Instance))
        {
            var kb = Encoding.UTF8.GetBytes(key);
            WriteHead(w, 3, (ulong)kb.Length);
            w.Write(kb);
            WriteValue(w, map[key]);
        }
    }

    private sealed class Utf8ByteComparer : IComparer<byte[]>
    {
        public static readonly Utf8ByteComparer Instance = new();
        public int Compare(byte[]? x, byte[]? y)
            => x.AsSpan().SequenceCompareTo(y.AsSpan());
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
            if (!Fill(n)) throw new EndOfStreamException("flatwire cbor: truncated value");
            var span = _buf.AsSpan(_pos, n);
            _pos += n;
            return span;
        }

        private byte U8() => Take(1)[0];

        private ulong Argument(int ai)
        {
            if (ai < 24) return (ulong)ai;
            return ai switch
            {
                24 => U8(),
                25 => BinaryPrimitives.ReadUInt16BigEndian(Take(2)),
                26 => BinaryPrimitives.ReadUInt32BigEndian(Take(4)),
                27 => BinaryPrimitives.ReadUInt64BigEndian(Take(8)),
                _ => throw new InvalidDataException($"flatwire cbor: unsupported additional info {ai}"),
            };
        }

        public object? ReadValue()
        {
            byte ib = U8();
            int major = ib >> 5;
            int ai = ib & 0x1f;
            switch (major)
            {
                case 0: return (long)Argument(ai);
                case 1: return -1L - (long)Argument(ai);
                case 2: return Take((int)Argument(ai)).ToArray();
                case 3: return Encoding.UTF8.GetString(Take((int)Argument(ai)));
                case 4:
                {
                    int n = (int)Argument(ai);
                    var a = new List<object?>(n);
                    for (int i = 0; i < n; i++) a.Add(ReadValue());
                    return a;
                }
                case 5:
                {
                    int n = (int)Argument(ai);
                    var m = new Dictionary<string, object?>(n);
                    for (int i = 0; i < n; i++)
                    {
                        var k = ReadValue();
                        m[Convert.ToString(k) ?? ""] = ReadValue();
                    }
                    return m;
                }
                case 7:
                    return ai switch
                    {
                        20 => false,
                        21 => true,
                        22 => (object?)null,
                        23 => null, // undefined -> null
                        25 => DecodeFloat16(Take(2)),
                        26 => (double)BinaryPrimitives.ReadSingleBigEndian(Take(4)),
                        27 => BinaryPrimitives.ReadDoubleBigEndian(Take(8)),
                        _ => throw new InvalidDataException($"flatwire cbor: unsupported simple value {ai}"),
                    };
                default:
                    throw new InvalidDataException($"flatwire cbor: unsupported major type {major}");
            }
        }

        private static double DecodeFloat16(ReadOnlySpan<byte> b)
        {
            ushort h = BinaryPrimitives.ReadUInt16BigEndian(b);
            int sign = (h >> 15) & 0x1;
            int exp = (h >> 10) & 0x1f;
            int frac = h & 0x3ff;
            double val;
            if (exp == 0) val = (frac / 1024.0) * Math.Pow(2, -14);
            else if (exp == 0x1f) val = frac == 0 ? double.PositiveInfinity : double.NaN;
            else val = (1.0 + frac / 1024.0) * Math.Pow(2, exp - 15);
            return sign == 1 ? -val : val;
        }
    }

    private sealed class BufferLite
    {
        private byte[] _buf = new byte[256];
        private int _len;
        public ReadOnlySpan<byte> Span => _buf.AsSpan(0, _len);
        public void Reset() => _len = 0;
        private void Ensure(int n) { if (_len + n > _buf.Length) Array.Resize(ref _buf, Math.Max(_buf.Length * 2, _len + n)); }
        public void WriteByte(byte b) { Ensure(1); _buf[_len++] = b; }
        public void Write(ReadOnlySpan<byte> s) { Ensure(s.Length); s.CopyTo(_buf.AsSpan(_len)); _len += s.Length; }
        public void WriteU16BE(ushort v) { Ensure(2); BinaryPrimitives.WriteUInt16BigEndian(_buf.AsSpan(_len), v); _len += 2; }
        public void WriteU32BE(uint v) { Ensure(4); BinaryPrimitives.WriteUInt32BigEndian(_buf.AsSpan(_len), v); _len += 4; }
        public void WriteU64BE(ulong v) { Ensure(8); BinaryPrimitives.WriteUInt64BigEndian(_buf.AsSpan(_len), v); _len += 8; }
        public void WriteDoubleBE(double v) { Ensure(8); BinaryPrimitives.WriteDoubleBigEndian(_buf.AsSpan(_len), v); _len += 8; }
    }
}
