package flatwire

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestWriteArraySetsContentTypeAndStreams(t *testing.T) {
	items := []any{
		map[string]any{"id": int64(1), "name": "a"},
		map[string]any{"id": int64(2), "name": "b"},
		int64(7),
	}
	for _, fmt := range []string{"json", "xml", "msgpack", "cbor"} {
		rec := httptest.NewRecorder()
		n, err := WriteArray(rec, items, fmt)
		if err != nil {
			t.Fatalf("%s: %v", fmt, err)
		}
		if n != len(items) {
			t.Fatalf("%s: wrote %d, want %d", fmt, n, len(items))
		}
		if got := rec.Header().Get("Content-Type"); got != MediaTypes[fmt] {
			t.Fatalf("%s: content-type %q, want %q", fmt, got, MediaTypes[fmt])
		}
		if rec.Body.Len() == 0 {
			t.Fatalf("%s: empty body", fmt)
		}
	}
}

func TestWriteArrayJSONRoundTrips(t *testing.T) {
	items := []any{map[string]any{"id": float64(1)}, map[string]any{"id": float64(2)}}
	rec := httptest.NewRecorder()
	if _, err := WriteArray(rec, items, "json"); err != nil {
		t.Fatal(err)
	}
	var out []map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &out); err != nil {
		t.Fatal(err)
	}
	if len(out) != 2 || out[1]["id"] != float64(2) {
		t.Fatalf("round-trip mismatch: %v", out)
	}
}

func TestWriteArrayUnknownFormat(t *testing.T) {
	rec := httptest.NewRecorder()
	if _, err := WriteArray(rec, []any{1}, "protobuf"); err == nil {
		t.Fatal("expected error for unknown format")
	}
}

func TestArrayHandler(t *testing.T) {
	h := ArrayHandler([]any{int64(1), int64(2), int64(3)}, "cbor")
	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/rows", nil)
	h.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("status %d", rec.Code)
	}
	if rec.Header().Get("Content-Type") != "application/cbor" {
		t.Fatalf("content-type %q", rec.Header().Get("Content-Type"))
	}
	// Decode the streamed CBOR back.
	var out []any
	if err := DecodeArrayCBOR(rec.Body, func(v any) error { out = append(out, v); return nil }); err != nil {
		t.Fatal(err)
	}
	if len(out) != 3 {
		t.Fatalf("decoded %d elements, want 3", len(out))
	}
}
