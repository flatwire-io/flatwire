package flatwire

import (
	"bytes"
	"encoding/hex"
	"reflect"
	"testing"
)

func TestCborRoundtrip(t *testing.T) {
	items := []any{
		map[string]any{"id": int64(1), "name": "row-1", "ok": true, "tags": []any{"a", "b"}, "note": nil},
		int64(42), int64(-7), int64(300), int64(-300), int64(100000),
		3.14159, -1.5, true, false, nil,
		"unïcode ✓ €uro 🎯",
		[]any{int64(1), []any{int64(2), int64(3)}, map[string]any{"k": "v"}},
	}
	var buf bytes.Buffer
	n, err := EncodeArrayCBOR(items, &buf)
	if err != nil || n != len(items) {
		t.Fatalf("encode: n=%d err=%v", n, err)
	}
	var out []any
	err = DecodeArrayCBOR(&buf, func(v any) error { out = append(out, v); return nil })
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(out, items) {
		t.Fatalf("round-trip mismatch:\n got %#v\nwant %#v", out, items)
	}
}

func TestCborCanonicalVectors(t *testing.T) {
	enc := func(v any) string {
		var b bytes.Buffer
		if _, err := EncodeArrayCBOR([]any{v}, &b); err != nil {
			t.Fatal(err)
		}
		return hex.EncodeToString(b.Bytes())
	}
	cases := map[string]string{
		enc(int64(0)):                              "00",
		enc(int64(23)):                             "17",
		enc(int64(24)):                             "1818",
		enc(int64(255)):                            "18ff",
		enc(int64(256)):                            "190100",
		enc(int64(-1)):                             "20",
		enc(int64(-24)):                            "37",
		enc(int64(-25)):                            "3818",
		enc(true):                                  "f5",
		enc(false):                                 "f4",
		enc(nil):                                   "f6",
		enc("a"):                                   "6161",
		enc([]any{int64(1), int64(2), int64(3)}):   "83010203",
		enc(map[string]any{"b": int64(2), "a": int64(1)}): "a2616101616202",
		enc(1.5):                                   "fb3ff8000000000000",
	}
	for got, want := range cases {
		if got != want {
			t.Fatalf("canonical vector mismatch: got %s want %s", got, want)
		}
	}
}

func TestCborMoreCompactThanJSON(t *testing.T) {
	items := make([]any, 0, 1000)
	for i := 0; i < 1000; i++ {
		items = append(items, map[string]any{"id": int64(i), "name": "row", "ok": i%2 == 0})
	}
	var jb, cb bytes.Buffer
	if _, err := EncodeArray(items, &jb); err != nil {
		t.Fatal(err)
	}
	if _, err := EncodeArrayCBOR(items, &cb); err != nil {
		t.Fatal(err)
	}
	if cb.Len() >= jb.Len() {
		t.Fatalf("expected cbor (%d) < json (%d)", cb.Len(), jb.Len())
	}
}
