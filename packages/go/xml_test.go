package flatwire

import (
	"bytes"
	"io"
	"reflect"
	"testing"
)

func TestXMLEncodeDecodeRoundtrip(t *testing.T) {
	items := []any{
		map[string]any{"id": int64(1), "name": "row-1", "ok": true, "tags": []any{"a", "b"}, "score": 3.5, "note": nil},
		map[string]any{"id": int64(2), "name": "has < & > \" chars", "ok": false},
		int64(42),
		"plain",
		[]any{int64(1), int64(2), int64(3)},
		nil,
		true,
	}
	var buf bytes.Buffer
	n, err := EncodeArrayXML(items, &buf, "items")
	if err != nil || n != len(items) {
		t.Fatalf("encode: n=%d err=%v", n, err)
	}

	var got []any
	err = DecodeArrayXML(&buf, "item", func(v any) error {
		got = append(got, v)
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(items, got) {
		t.Fatalf("xml roundtrip mismatch:\n got %#v\n want %#v", got, items)
	}
}

// A reader that returns a few bytes at a time, to force element boundaries to
// land mid-read.
type trickle struct {
	data []byte
	pos  int
}

func (tr *trickle) Read(p []byte) (int, error) {
	if tr.pos >= len(tr.data) {
		return 0, io.EOF
	}
	n := len(p)
	if n > 7 {
		n = 7
	}
	if n > len(tr.data)-tr.pos {
		n = len(tr.data) - tr.pos
	}
	copy(p, tr.data[tr.pos:tr.pos+n])
	tr.pos += n
	return n, nil
}

func TestXMLStreamsAcrossSmallReads(t *testing.T) {
	items := make([]any, 1000)
	for i := range items {
		items[i] = map[string]any{"id": int64(i), "name": "row", "vals": []any{int64(i), int64(i + 1)}}
	}
	var buf bytes.Buffer
	if _, err := EncodeArrayXML(items, &buf, "items"); err != nil {
		t.Fatal(err)
	}
	tr := &trickle{data: buf.Bytes()}
	var got []any
	err := DecodeArrayXML(tr, "item", func(v any) error {
		got = append(got, v)
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 1000 {
		t.Fatalf("expected 1000 elements, got %d", len(got))
	}
	if !reflect.DeepEqual(items[500], got[500]) {
		t.Fatalf("element 500 mismatch: %#v vs %#v", got[500], items[500])
	}
}
