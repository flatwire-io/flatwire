package flatwire

import (
	"bytes"
	"encoding/json"
	"strings"
	"testing"
)

func TestCheckedCleanCompletion(t *testing.T) {
	items := make([]row, 0, 500)
	for i := 0; i < 500; i++ {
		items = append(items, row{ID: i, Name: "r", OK: true})
	}
	var buf bytes.Buffer
	n, err := EncodeCheckedArray(items, &buf)
	if err != nil || n != 500 {
		t.Fatalf("encode: n=%d err=%v", n, err)
	}

	count := 0
	var last row
	err = DecodeCheckedArray(&buf, func(raw json.RawMessage) error {
		var r row
		if err := json.Unmarshal(raw, &r); err != nil {
			return err
		}
		last = r
		count++
		return nil
	})
	if err != nil {
		t.Fatalf("clean stream must not error: %v", err)
	}
	if count != 500 || last.ID != 499 {
		t.Fatalf("count=%d last=%+v", count, last)
	}
}

func TestCheckedProducerError(t *testing.T) {
	// Reference wire form: two items then an error trailer.
	wire := `{"items":[1,2],"complete":false,"error":{"message":"boom","type":"ValueError"}}`
	var got []int
	err := DecodeCheckedArray(strings.NewReader(wire), func(raw json.RawMessage) error {
		var n int
		if err := json.Unmarshal(raw, &n); err != nil {
			return err
		}
		got = append(got, n)
		return nil
	})
	se, ok := err.(*StreamError)
	if !ok {
		t.Fatalf("expected *StreamError, got %T (%v)", err, err)
	}
	if len(got) != 2 || got[0] != 1 || got[1] != 2 {
		t.Fatalf("items before error = %v", got)
	}
	if !strings.Contains(string(se.Err), "boom") {
		t.Fatalf("error payload = %s", se.Err)
	}
}

func TestCheckedTruncation(t *testing.T) {
	var buf bytes.Buffer
	if _, err := EncodeCheckedArray([]int{1, 2, 3, 4}, &buf); err != nil {
		t.Fatal(err)
	}
	full := buf.Bytes()
	terminal := `],"complete":true}`
	cut := full[:len(full)-len(terminal)] // drop the whole terminal status

	err := DecodeCheckedArray(bytes.NewReader(cut), func(raw json.RawMessage) error { return nil })
	if _, ok := err.(*TruncatedStreamError); !ok {
		t.Fatalf("expected *TruncatedStreamError, got %T (%v)", err, err)
	}
}

func TestCheckedInteropEnvelope(t *testing.T) {
	wire := `{"items":[{"id":1,"name":"a","ok":true},{"id":2,"name":"b","ok":false}],"complete":true}`
	var rows []row
	err := DecodeCheckedArray(strings.NewReader(wire), func(raw json.RawMessage) error {
		var r row
		if err := json.Unmarshal(raw, &r); err != nil {
			return err
		}
		rows = append(rows, r)
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(rows) != 2 || rows[1].Name != "b" {
		t.Fatalf("rows = %+v", rows)
	}
}
