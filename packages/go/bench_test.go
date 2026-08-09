package flatwire

// Benchmarks: encoding/json materialized vs flatwire streaming, using Go's
// native testing harness. Run:
//
//	go test -bench . -benchmem ./...
//
// -benchmem reports B/op (bytes allocated per operation) and allocs/op, which is
// exactly the memory axis that matters: streaming keeps B/op flat with respect
// to collection size, while materializing scales with it.

import (
	"bytes"
	"encoding/json"
	"io"
	"testing"
)

type benchRow struct {
	ID      int    `json:"id"`
	Name    string `json:"name"`
	Payload string `json:"payload"`
	OK      bool   `json:"ok"`
}

func makeBenchRows(n int) []benchRow {
	items := make([]benchRow, n)
	pay := ""
	for i := 0; i < 200; i++ {
		pay += "x"
	}
	for i := range items {
		items[i] = benchRow{ID: i, Name: "row", Payload: pay, OK: i%2 == 0}
	}
	return items
}

var benchSizes = []int{1000, 10000, 50000}

func BenchmarkEncodeWhole(b *testing.B) {
	for _, n := range benchSizes {
		items := makeBenchRows(n)
		b.Run(sizeName(n), func(b *testing.B) {
			b.ReportAllocs()
			for i := 0; i < b.N; i++ {
				out, _ := json.Marshal(items) // materialize whole []byte
				_ = out
			}
		})
	}
}

func BenchmarkEncodeStream(b *testing.B) {
	for _, n := range benchSizes {
		items := makeBenchRows(n)
		b.Run(sizeName(n), func(b *testing.B) {
			b.ReportAllocs()
			for i := 0; i < b.N; i++ {
				_, _ = EncodeArray(items, io.Discard) // stream, flat memory
			}
		})
	}
}

func BenchmarkAggregateWhole(b *testing.B) {
	for _, n := range benchSizes {
		blob, _ := json.Marshal(makeBenchRows(n))
		b.Run(sizeName(n), func(b *testing.B) {
			b.ReportAllocs()
			for i := 0; i < b.N; i++ {
				var all []benchRow
				_ = json.Unmarshal(blob, &all)
				total := 0
				for _, r := range all {
					total += r.ID
				}
				_ = total
			}
		})
	}
}

func BenchmarkAggregateStream(b *testing.B) {
	for _, n := range benchSizes {
		blob, _ := json.Marshal(makeBenchRows(n))
		b.Run(sizeName(n), func(b *testing.B) {
			b.ReportAllocs()
			for i := 0; i < b.N; i++ {
				total := 0
				_ = DecodeArray(bytes.NewReader(blob), func(raw json.RawMessage) error {
					var r benchRow
					if err := json.Unmarshal(raw, &r); err != nil {
						return err
					}
					total += r.ID
					return nil
				})
				_ = total
			}
		})
	}
}

func sizeName(n int) string {
	switch {
	case n >= 1000:
		return itoa(n/1000) + "k"
	default:
		return itoa(n)
	}
}

func itoa(n int) string {
	if n == 0 {
		return "0"
	}
	neg := n < 0
	if neg {
		n = -n
	}
	var buf [20]byte
	i := len(buf)
	for n > 0 {
		i--
		buf[i] = byte('0' + n%10)
		n /= 10
	}
	if neg {
		i--
		buf[i] = '-'
	}
	return string(buf[i:])
}
