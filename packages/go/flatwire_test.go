package flatwire

import (
	"bytes"
	"encoding/json"
	"reflect"
	"testing"
)

type row struct {
	ID   int    `json:"id"`
	Name string `json:"name"`
	OK   bool   `json:"ok"`
}

func TestEncodeDecodeRoundtrip(t *testing.T) {
	in := map[string]any{"a": float64(1), "b": []any{float64(1), float64(2)}}
	b, err := Encode(in)
	if err != nil {
		t.Fatal(err)
	}
	var out map[string]any
	if err := Decode(b, &out); err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(in, out) {
		t.Fatalf("roundtrip mismatch: %v != %v", in, out)
	}
}

func TestEncodeArrayThenDecodeArray(t *testing.T) {
	items := make([]row, 1000)
	for i := range items {
		items[i] = row{ID: i, Name: "row", OK: i%2 == 0}
	}
	var buf bytes.Buffer
	n, err := EncodeArray(items, &buf)
	if err != nil || n != 1000 {
		t.Fatalf("encode: n=%d err=%v", n, err)
	}
	// Valid ordinary JSON array.
	var whole []row
	if err := json.Unmarshal(buf.Bytes(), &whole); err != nil {
		t.Fatal(err)
	}
	if len(whole) != 1000 || whole[500].ID != 500 {
		t.Fatalf("whole wrong: len=%d", len(whole))
	}
	// Streaming decode yields every element.
	var got []row
	err = DecodeArray(bytes.NewReader(buf.Bytes()), func(raw json.RawMessage) error {
		var r row
		if err := json.Unmarshal(raw, &r); err != nil {
			return err
		}
		got = append(got, r)
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(items, got) {
		t.Fatalf("streamed mismatch: len %d vs %d", len(items), len(got))
	}
}

func TestDecodeArrayTrickyStrings(t *testing.T) {
	tricky := []string{"has, comma and ] bracket", "plain", "v,]["}
	var buf bytes.Buffer
	if _, err := EncodeArray(tricky, &buf); err != nil {
		t.Fatal(err)
	}
	var got []string
	err := DecodeArray(&buf, func(raw json.RawMessage) error {
		var s string
		if err := json.Unmarshal(raw, &s); err != nil {
			return err
		}
		got = append(got, s)
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(tricky, got) {
		t.Fatalf("tricky mismatch: %v", got)
	}
}

func TestDecodeArrayRejectsNonArray(t *testing.T) {
	err := DecodeArray(bytes.NewReader([]byte(`{"not":"array"}`)), func(json.RawMessage) error { return nil })
	if err == nil {
		t.Fatal("expected error for non-array input")
	}
}
