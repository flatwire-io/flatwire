package flatwire

// Streaming CBOR (RFC 8949 binary) format for flatwire, mirroring the Python
// reference. flatwire's CBOR wire is a stream of concatenated CBOR data items
// (not a length-prefixed array), so encoding needs no upfront count and decoding
// reads one item at a time. The encoding is deterministic (shortest heads, map
// keys sorted by UTF-8 bytes, 64-bit floats), so output is byte-identical across
// all six flatwire languages. Covers the JSON data model
// (null/bool/int/float/str/array/map); no tags.
//
// Values are Go's generic any: objects -> map[string]any, arrays -> []any,
// scalars -> int64/uint64/float64/bool/string/nil.

import (
	"bufio"
	"encoding/binary"
	"fmt"
	"io"
	"math"
	"sort"
)

// --- encoding --------------------------------------------------------------

func writeCborHead(w io.Writer, major byte, n uint64) error {
	mt := major << 5
	switch {
	case n < 24:
		_, err := w.Write([]byte{mt | byte(n)})
		return err
	case n <= 0xff:
		_, err := w.Write([]byte{mt | 24, byte(n)})
		return err
	case n <= 0xffff:
		var b [3]byte
		b[0] = mt | 25
		binary.BigEndian.PutUint16(b[1:], uint16(n))
		_, err := w.Write(b[:])
		return err
	case n <= 0xffffffff:
		var b [5]byte
		b[0] = mt | 26
		binary.BigEndian.PutUint32(b[1:], uint32(n))
		_, err := w.Write(b[:])
		return err
	default:
		var b [9]byte
		b[0] = mt | 27
		binary.BigEndian.PutUint64(b[1:], n)
		_, err := w.Write(b[:])
		return err
	}
}

func writeCborValue(w io.Writer, v any) error {
	switch x := v.(type) {
	case nil:
		_, err := w.Write([]byte{0xf6})
		return err
	case bool:
		if x {
			_, err := w.Write([]byte{0xf5})
			return err
		}
		_, err := w.Write([]byte{0xf4})
		return err
	case string:
		if err := writeCborHead(w, 3, uint64(len(x))); err != nil {
			return err
		}
		_, err := io.WriteString(w, x)
		return err
	case float32:
		return writeCborF64(w, float64(x))
	case float64:
		return writeCborF64(w, x)
	case int:
		return writeCborInt(w, int64(x))
	case int8:
		return writeCborInt(w, int64(x))
	case int16:
		return writeCborInt(w, int64(x))
	case int32:
		return writeCborInt(w, int64(x))
	case int64:
		return writeCborInt(w, x)
	case uint:
		return writeCborHead(w, 0, uint64(x))
	case uint8:
		return writeCborHead(w, 0, uint64(x))
	case uint16:
		return writeCborHead(w, 0, uint64(x))
	case uint32:
		return writeCborHead(w, 0, uint64(x))
	case uint64:
		return writeCborHead(w, 0, x)
	case []any:
		if err := writeCborHead(w, 4, uint64(len(x))); err != nil {
			return err
		}
		for _, e := range x {
			if err := writeCborValue(w, e); err != nil {
				return err
			}
		}
		return nil
	case map[string]any:
		if err := writeCborHead(w, 5, uint64(len(x))); err != nil {
			return err
		}
		// Deterministic: sort keys by their UTF-8 byte sequence (Go string
		// ordering is byte-wise on UTF-8).
		keys := make([]string, 0, len(x))
		for k := range x {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		for _, k := range keys {
			if err := writeCborHead(w, 3, uint64(len(k))); err != nil {
				return err
			}
			if _, err := io.WriteString(w, k); err != nil {
				return err
			}
			if err := writeCborValue(w, x[k]); err != nil {
				return err
			}
		}
		return nil
	default:
		return fmt.Errorf("flatwire cbor: unsupported type %T", v)
	}
}

func writeCborInt(w io.Writer, v int64) error {
	if v >= 0 {
		return writeCborHead(w, 0, uint64(v))
	}
	return writeCborHead(w, 1, uint64(-1-v))
}

func writeCborF64(w io.Writer, f float64) error {
	var b [9]byte
	b[0] = 0xfb
	binary.BigEndian.PutUint64(b[1:], math.Float64bits(f))
	_, err := w.Write(b[:])
	return err
}

// EncodeArrayCBOR streams a collection as concatenated CBOR data items, one per
// element. Peak memory is bounded by the largest single element. Returns the
// element count.
func EncodeArrayCBOR(items []any, w io.Writer) (int, error) {
	count := 0
	for _, v := range items {
		if err := writeCborValue(w, v); err != nil {
			return count, err
		}
		count++
	}
	return count, nil
}

// --- decoding --------------------------------------------------------------

// DecodeArrayCBOR lazily reads concatenated CBOR data items, calling yield with
// each decoded element in turn. Backed by a buffered reader, so the whole stream
// is never held in memory at once.
func DecodeArrayCBOR(r io.Reader, yield func(any) error) error {
	br := bufio.NewReaderSize(r, 65536)
	for {
		_, err := br.Peek(1)
		if err == io.EOF {
			return nil
		}
		if err != nil {
			return err
		}
		v, err := readCborValue(br)
		if err != nil {
			return err
		}
		if err := yield(v); err != nil {
			return err
		}
	}
}

func readCborArgument(br *bufio.Reader, ai byte) (uint64, error) {
	switch {
	case ai < 24:
		return uint64(ai), nil
	case ai == 24:
		b, err := br.ReadByte()
		return uint64(b), err
	case ai == 25:
		b, err := readN(br, 2)
		if err != nil {
			return 0, err
		}
		return uint64(binary.BigEndian.Uint16(b)), nil
	case ai == 26:
		b, err := readN(br, 4)
		if err != nil {
			return 0, err
		}
		return uint64(binary.BigEndian.Uint32(b)), nil
	case ai == 27:
		b, err := readN(br, 8)
		if err != nil {
			return 0, err
		}
		return binary.BigEndian.Uint64(b), nil
	default:
		return 0, fmt.Errorf("flatwire cbor: unsupported additional info %d", ai)
	}
}

func readCborValue(br *bufio.Reader) (any, error) {
	ib, err := br.ReadByte()
	if err != nil {
		return nil, err
	}
	major := ib >> 5
	ai := ib & 0x1f
	switch major {
	case 0:
		n, err := readCborArgument(br, ai)
		if err != nil {
			return nil, err
		}
		if n <= math.MaxInt64 {
			return int64(n), nil
		}
		return n, nil
	case 1:
		n, err := readCborArgument(br, ai)
		if err != nil {
			return nil, err
		}
		return int64(-1 - int64(n)), nil
	case 2:
		return nil, fmt.Errorf("flatwire cbor: byte-string is not part of the JSON value model")
	case 3:
		n, err := readCborArgument(br, ai)
		if err != nil {
			return nil, err
		}
		b, err := readN(br, int(n))
		if err != nil {
			return nil, err
		}
		return string(b), nil
	case 4:
		n, err := readCborArgument(br, ai)
		if err != nil {
			return nil, err
		}
		arr := make([]any, n)
		for i := 0; i < int(n); i++ {
			e, err := readCborValue(br)
			if err != nil {
				return nil, err
			}
			arr[i] = e
		}
		return arr, nil
	case 5:
		n, err := readCborArgument(br, ai)
		if err != nil {
			return nil, err
		}
		m := make(map[string]any, n)
		for i := 0; i < int(n); i++ {
			k, err := readCborValue(br)
			if err != nil {
				return nil, err
			}
			val, err := readCborValue(br)
			if err != nil {
				return nil, err
			}
			key, ok := k.(string)
			if !ok {
				key = fmt.Sprintf("%v", k)
			}
			m[key] = val
		}
		return m, nil
	case 7:
		switch ai {
		case 20:
			return false, nil
		case 21:
			return true, nil
		case 22:
			return nil, nil
		case 23:
			return nil, nil // undefined -> null
		case 25:
			b, err := readN(br, 2)
			if err != nil {
				return nil, err
			}
			return decodeCborF16(binary.BigEndian.Uint16(b)), nil
		case 26:
			b, err := readN(br, 4)
			if err != nil {
				return nil, err
			}
			return float64(math.Float32frombits(binary.BigEndian.Uint32(b))), nil
		case 27:
			b, err := readN(br, 8)
			if err != nil {
				return nil, err
			}
			return math.Float64frombits(binary.BigEndian.Uint64(b)), nil
		default:
			return nil, fmt.Errorf("flatwire cbor: unsupported simple value %d", ai)
		}
	default:
		return nil, fmt.Errorf("flatwire cbor: unsupported major type %d", major)
	}
}

func decodeCborF16(h uint16) float64 {
	sign := (h >> 15) & 0x1
	exp := (h >> 10) & 0x1f
	frac := h & 0x3ff
	var val float64
	switch {
	case exp == 0:
		val = (float64(frac) / 1024.0) * math.Pow(2, -14)
	case exp == 0x1f:
		if frac == 0 {
			val = math.Inf(1)
		} else {
			val = math.NaN()
		}
	default:
		val = (1.0 + float64(frac)/1024.0) * math.Pow(2, float64(exp)-15)
	}
	if sign == 1 {
		return -val
	}
	return val
}
