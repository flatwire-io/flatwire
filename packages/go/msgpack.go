package flatwire

// Streaming MessagePack (binary) format for flatwire, mirroring the Python
// reference. flatwire's binary wire is a stream of concatenated MessagePack
// values (not a length-prefixed array), so encoding needs no upfront count and
// decoding reads one value at a time. Wire-compatible with standard MessagePack
// for the JSON data model (null/bool/int/float/str/array/map); no ext types.
//
// Values are Go's generic any: objects -> map[string]any, arrays -> []any,
// scalars -> int64/uint64/float64/bool/string/nil.

import (
	"bufio"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"math"
)

// --- encoding --------------------------------------------------------------

func writeMsgValue(w io.Writer, v any) error {
	switch x := v.(type) {
	case nil:
		_, err := w.Write([]byte{0xc0})
		return err
	case bool:
		if x {
			_, err := w.Write([]byte{0xc3})
			return err
		}
		_, err := w.Write([]byte{0xc2})
		return err
	case string:
		return writeMsgStr(w, x)
	case float32:
		return writeMsgF64(w, float64(x))
	case float64:
		return writeMsgF64(w, x)
	case int:
		return writeMsgInt(w, int64(x))
	case int8:
		return writeMsgInt(w, int64(x))
	case int16:
		return writeMsgInt(w, int64(x))
	case int32:
		return writeMsgInt(w, int64(x))
	case int64:
		return writeMsgInt(w, x)
	case uint:
		return writeMsgUint(w, uint64(x))
	case uint8:
		return writeMsgUint(w, uint64(x))
	case uint16:
		return writeMsgUint(w, uint64(x))
	case uint32:
		return writeMsgUint(w, uint64(x))
	case uint64:
		return writeMsgUint(w, x)
	case []any:
		if err := writeMsgArrayHeader(w, len(x)); err != nil {
			return err
		}
		for _, e := range x {
			if err := writeMsgValue(w, e); err != nil {
				return err
			}
		}
		return nil
	case map[string]any:
		if err := writeMsgMapHeader(w, len(x)); err != nil {
			return err
		}
		for k, val := range x {
			if err := writeMsgStr(w, k); err != nil {
				return err
			}
			if err := writeMsgValue(w, val); err != nil {
				return err
			}
		}
		return nil
	default:
		return fmt.Errorf("flatwire msgpack: unsupported type %T", v)
	}
}

func writeMsgF64(w io.Writer, f float64) error {
	var b [9]byte
	b[0] = 0xcb
	binary.BigEndian.PutUint64(b[1:], math.Float64bits(f))
	_, err := w.Write(b[:])
	return err
}

func writeMsgInt(w io.Writer, v int64) error {
	switch {
	case v >= 0 && v <= 0x7f:
		_, err := w.Write([]byte{byte(v)})
		return err
	case v < 0 && v >= -32:
		_, err := w.Write([]byte{byte(v)})
		return err
	case v >= -0x80 && v <= 0x7f:
		_, err := w.Write([]byte{0xd0, byte(v)})
		return err
	case v >= -0x8000 && v <= 0x7fff:
		var b [3]byte
		b[0] = 0xd1
		binary.BigEndian.PutUint16(b[1:], uint16(int16(v)))
		_, err := w.Write(b[:])
		return err
	case v >= -0x80000000 && v <= 0x7fffffff:
		var b [5]byte
		b[0] = 0xd2
		binary.BigEndian.PutUint32(b[1:], uint32(int32(v)))
		_, err := w.Write(b[:])
		return err
	default:
		var b [9]byte
		b[0] = 0xd3
		binary.BigEndian.PutUint64(b[1:], uint64(v))
		_, err := w.Write(b[:])
		return err
	}
}

func writeMsgUint(w io.Writer, v uint64) error {
	switch {
	case v <= 0x7f:
		_, err := w.Write([]byte{byte(v)})
		return err
	case v <= 0xff:
		_, err := w.Write([]byte{0xcc, byte(v)})
		return err
	case v <= 0xffff:
		var b [3]byte
		b[0] = 0xcd
		binary.BigEndian.PutUint16(b[1:], uint16(v))
		_, err := w.Write(b[:])
		return err
	case v <= 0xffffffff:
		var b [5]byte
		b[0] = 0xce
		binary.BigEndian.PutUint32(b[1:], uint32(v))
		_, err := w.Write(b[:])
		return err
	default:
		var b [9]byte
		b[0] = 0xcf
		binary.BigEndian.PutUint64(b[1:], v)
		_, err := w.Write(b[:])
		return err
	}
}

func writeMsgStr(w io.Writer, s string) error {
	n := len(s)
	switch {
	case n <= 31:
		if _, err := w.Write([]byte{0xa0 | byte(n)}); err != nil {
			return err
		}
	case n <= 0xff:
		if _, err := w.Write([]byte{0xd9, byte(n)}); err != nil {
			return err
		}
	case n <= 0xffff:
		var b [3]byte
		b[0] = 0xda
		binary.BigEndian.PutUint16(b[1:], uint16(n))
		if _, err := w.Write(b[:]); err != nil {
			return err
		}
	default:
		var b [5]byte
		b[0] = 0xdb
		binary.BigEndian.PutUint32(b[1:], uint32(n))
		if _, err := w.Write(b[:]); err != nil {
			return err
		}
	}
	_, err := io.WriteString(w, s)
	return err
}

func writeMsgArrayHeader(w io.Writer, n int) error {
	switch {
	case n <= 15:
		_, err := w.Write([]byte{0x90 | byte(n)})
		return err
	case n <= 0xffff:
		var b [3]byte
		b[0] = 0xdc
		binary.BigEndian.PutUint16(b[1:], uint16(n))
		_, err := w.Write(b[:])
		return err
	default:
		var b [5]byte
		b[0] = 0xdd
		binary.BigEndian.PutUint32(b[1:], uint32(n))
		_, err := w.Write(b[:])
		return err
	}
}

func writeMsgMapHeader(w io.Writer, n int) error {
	switch {
	case n <= 15:
		_, err := w.Write([]byte{0x80 | byte(n)})
		return err
	case n <= 0xffff:
		var b [3]byte
		b[0] = 0xde
		binary.BigEndian.PutUint16(b[1:], uint16(n))
		_, err := w.Write(b[:])
		return err
	default:
		var b [5]byte
		b[0] = 0xdf
		binary.BigEndian.PutUint32(b[1:], uint32(n))
		_, err := w.Write(b[:])
		return err
	}
}

// EncodeArrayMsgPack streams a collection as concatenated MessagePack values, one
// per element. Peak memory is bounded by the largest single element. Returns the
// element count.
func EncodeArrayMsgPack(items []any, w io.Writer) (int, error) {
	count := 0
	for _, v := range items {
		if err := writeMsgValue(w, v); err != nil {
			return count, err
		}
		count++
	}
	return count, nil
}

// --- decoding --------------------------------------------------------------

// DecodeArrayMsgPack lazily reads concatenated MessagePack values, calling yield
// with each decoded element in turn. Backed by a buffered reader, so the whole
// stream is never held in memory at once.
func DecodeArrayMsgPack(r io.Reader, yield func(any) error) error {
	br := bufio.NewReaderSize(r, 65536)
	for {
		_, err := br.Peek(1)
		if err == io.EOF {
			return nil
		}
		if err != nil {
			return err
		}
		v, err := readMsgValue(br)
		if err != nil {
			return err
		}
		if err := yield(v); err != nil {
			return err
		}
	}
}

func readMsgValue(br *bufio.Reader) (any, error) {
	c, err := br.ReadByte()
	if err != nil {
		return nil, err
	}
	switch {
	case c <= 0x7f:
		return int64(c), nil
	case c >= 0xe0:
		return int64(int8(c)), nil
	case c >= 0x80 && c <= 0x8f:
		return readMsgMap(br, int(c&0x0f))
	case c >= 0x90 && c <= 0x9f:
		return readMsgArray(br, int(c&0x0f))
	case c >= 0xa0 && c <= 0xbf:
		return readMsgStr(br, int(c&0x1f))
	}
	switch c {
	case 0xc0:
		return nil, nil
	case 0xc2:
		return false, nil
	case 0xc3:
		return true, nil
	case 0xca:
		b, err := readN(br, 4)
		if err != nil {
			return nil, err
		}
		return float64(math.Float32frombits(binary.BigEndian.Uint32(b))), nil
	case 0xcb:
		b, err := readN(br, 8)
		if err != nil {
			return nil, err
		}
		return math.Float64frombits(binary.BigEndian.Uint64(b)), nil
	case 0xcc:
		b, err := br.ReadByte()
		return int64(b), err
	case 0xcd:
		b, err := readN(br, 2)
		if err != nil {
			return nil, err
		}
		return int64(binary.BigEndian.Uint16(b)), nil
	case 0xce:
		b, err := readN(br, 4)
		if err != nil {
			return nil, err
		}
		return int64(binary.BigEndian.Uint32(b)), nil
	case 0xcf:
		b, err := readN(br, 8)
		if err != nil {
			return nil, err
		}
		return binary.BigEndian.Uint64(b), nil
	case 0xd0:
		b, err := br.ReadByte()
		return int64(int8(b)), err
	case 0xd1:
		b, err := readN(br, 2)
		if err != nil {
			return nil, err
		}
		return int64(int16(binary.BigEndian.Uint16(b))), nil
	case 0xd2:
		b, err := readN(br, 4)
		if err != nil {
			return nil, err
		}
		return int64(int32(binary.BigEndian.Uint32(b))), nil
	case 0xd3:
		b, err := readN(br, 8)
		if err != nil {
			return nil, err
		}
		return int64(binary.BigEndian.Uint64(b)), nil
	case 0xd9:
		n, err := br.ReadByte()
		if err != nil {
			return nil, err
		}
		return readMsgStr(br, int(n))
	case 0xda:
		b, err := readN(br, 2)
		if err != nil {
			return nil, err
		}
		return readMsgStr(br, int(binary.BigEndian.Uint16(b)))
	case 0xdb:
		b, err := readN(br, 4)
		if err != nil {
			return nil, err
		}
		return readMsgStr(br, int(binary.BigEndian.Uint32(b)))
	case 0xdc:
		b, err := readN(br, 2)
		if err != nil {
			return nil, err
		}
		return readMsgArray(br, int(binary.BigEndian.Uint16(b)))
	case 0xdd:
		b, err := readN(br, 4)
		if err != nil {
			return nil, err
		}
		return readMsgArray(br, int(binary.BigEndian.Uint32(b)))
	case 0xde:
		b, err := readN(br, 2)
		if err != nil {
			return nil, err
		}
		return readMsgMap(br, int(binary.BigEndian.Uint16(b)))
	case 0xdf:
		b, err := readN(br, 4)
		if err != nil {
			return nil, err
		}
		return readMsgMap(br, int(binary.BigEndian.Uint32(b)))
	case 0xc4, 0xc5, 0xc6:
		return nil, errors.New("flatwire msgpack: binary (bin) type is not part of the JSON value model")
	}
	return nil, fmt.Errorf("flatwire msgpack: unknown prefix 0x%02x", c)
}

func readN(br *bufio.Reader, n int) ([]byte, error) {
	b := make([]byte, n)
	_, err := io.ReadFull(br, b)
	return b, err
}

func readMsgStr(br *bufio.Reader, n int) (any, error) {
	b, err := readN(br, n)
	if err != nil {
		return nil, err
	}
	return string(b), nil
}

func readMsgArray(br *bufio.Reader, n int) (any, error) {
	arr := make([]any, n)
	for i := 0; i < n; i++ {
		v, err := readMsgValue(br)
		if err != nil {
			return nil, err
		}
		arr[i] = v
	}
	return arr, nil
}

func readMsgMap(br *bufio.Reader, n int) (any, error) {
	m := make(map[string]any, n)
	for i := 0; i < n; i++ {
		k, err := readMsgValue(br)
		if err != nil {
			return nil, err
		}
		v, err := readMsgValue(br)
		if err != nil {
			return nil, err
		}
		key, ok := k.(string)
		if !ok {
			key = fmt.Sprintf("%v", k)
		}
		m[key] = v
	}
	return m, nil
}
