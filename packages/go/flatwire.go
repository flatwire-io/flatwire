// Package flatwire provides streaming JSON serialization that keeps memory flat
// and time linear. The array helpers are the point: a large collection is
// written and read one element at a time, so peak memory is bounded by the
// largest single element rather than the whole collection. Wire format is plain
// JSON via encoding/json.
package flatwire

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
)

// Encode encodes a whole value to JSON bytes.
func Encode(v any) ([]byte, error) {
	return json.Marshal(v)
}

// Decode decodes JSON bytes into the target pointed to by v.
func Decode(data []byte, v any) error {
	return json.Unmarshal(data, v)
}

// EncodeTo streams a value straight to a writer via json.Encoder (no full
// intermediate copy).
func EncodeTo(v any, w io.Writer) error {
	return json.NewEncoder(w).Encode(v)
}

// DecodeFrom reads a whole value from a reader into v.
func DecodeFrom(r io.Reader, v any) error {
	return json.NewDecoder(r).Decode(v)
}

// EncodeArray streams a collection as a JSON array, one element at a time. Peak
// memory is bounded by the largest single element, not the collection length.
// It returns the number of elements written.
func EncodeArray[T any](items []T, w io.Writer) (int, error) {
	if _, err := io.WriteString(w, "["); err != nil {
		return 0, err
	}
	count := 0
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	for _, item := range items {
		if count > 0 {
			if _, err := io.WriteString(w, ","); err != nil {
				return count, err
			}
		}
		buf.Reset()
		if err := enc.Encode(item); err != nil {
			return count, err
		}
		// enc.Encode appends a newline; trim it so the array is compact.
		b := bytes.TrimRight(buf.Bytes(), "\n")
		if _, err := w.Write(b); err != nil {
			return count, err
		}
		count++
	}
	if _, err := io.WriteString(w, "]"); err != nil {
		return count, err
	}
	return count, nil
}

// DecodeArray lazily reads a top-level JSON array from r, calling yield with the
// raw bytes of each element in turn. It is backed by the stdlib streaming
// decoder, so the whole array is never held in memory at once. Returning a
// non-nil error from yield stops the iteration.
func DecodeArray(r io.Reader, yield func(json.RawMessage) error) error {
	dec := json.NewDecoder(r)
	tok, err := dec.Token()
	if err != nil {
		return err
	}
	if d, ok := tok.(json.Delim); !ok || d != '[' {
		return errors.New("flatwire: DecodeArray expects a top-level JSON array")
	}
	for dec.More() {
		var raw json.RawMessage
		if err := dec.Decode(&raw); err != nil {
			return err
		}
		if err := yield(raw); err != nil {
			return err
		}
	}
	_, err = dec.Token() // closing ']'
	return err
}
