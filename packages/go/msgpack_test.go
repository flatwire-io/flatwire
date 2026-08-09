package flatwire

import (
	"bytes"
	"encoding/json"
	"io"
	"reflect"
	"testing"
)

func TestMsgPackEncodeDecodeRoundtrip(t *testing.T) {
	items := []any{
		map[string]any{"id": int64(1), "name": "row-1", "ok": true, "tags": []any{"a", "b"}, "score": 3.5, "note": nil},
		int64(42), int64(-7), int64(300), int64(-300), int64(100000),
		"unïcode ✓ €", []any{int64(1), int64(2), int64(3)}, nil, true, 3.14159, -1.5,
	}
	var buf bytes.Buffer
	n, err := EncodeArrayMsgPack(items, &buf)
	if err != nil || n != len(items) {
		t.Fatalf("encode: n=%d err=%v", n, err)
	}
	var got []any
	err = DecodeArrayMsgPack(&buf, func(v any) error {
		got = append(got, v)
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(items, got) {
		t.Fatalf("msgpack roundtrip mismatch:\n got %#v\n want %#v", got, items)
	}
}

func TestMsgPackMoreCompactThanJSON(t *testing.T) {
	items := make([]any, 1000)
	for i := range items {
		items[i] = map[string]any{"id": int64(i), "name": "row", "ok": i%2 == 0}
	}
	var mp bytes.Buffer
	if _, err := EncodeArrayMsgPack(items, &mp); err != nil {
		t.Fatal(err)
	}
	jsonBytes, _ := json.Marshal(items)
	if mp.Len() >= len(jsonBytes) {
		t.Fatalf("expected msgpack (%d) < json (%d)", mp.Len(), len(jsonBytes))
	}
}

func TestMsgPackStreamsAcrossSmallReads(t *testing.T) {
	items := make([]any, 2000)
	for i := range items {
		items[i] = map[string]any{"id": int64(i), "vals": []any{int64(i), int64(i + 1)}}
	}
	var buf bytes.Buffer
	if _, err := EncodeArrayMsgPack(items, &buf); err != nil {
		t.Fatal(err)
	}
	tr := &trickle{data: buf.Bytes()}
	var got []any
	err := DecodeArrayMsgPack(tr, func(v any) error {
		got = append(got, v)
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 2000 {
		t.Fatalf("expected 2000 elements, got %d", len(got))
	}
	if !reflect.DeepEqual(items[1000], got[1000]) {
		t.Fatalf("element 1000 mismatch")
	}
}

// Ensure trickle satisfies io.Reader with EOF (declared in xml_test.go too, but
// guard against build issues if that file changes).
var _ io.Reader = (*trickle)(nil)
