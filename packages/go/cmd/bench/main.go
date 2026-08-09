// Command bench measures PEAK live heap (runtime.MemStats.HeapAlloc) during
// materialized vs streaming JSON operations - the metric that matters for flatwire's
// flat-memory claim. Go's built-in `go test -benchmem` reports *cumulative*
// bytes allocated per op, which counts every per-element allocation and so does
// not reflect peak live memory; this program samples HeapAlloc on a background
// goroutine to capture the peak instead.
//
// Run:  go run ./cmd/bench
package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"runtime"
	"sync/atomic"
	"time"

	flatwire "github.com/flatwire-io/flatwire/packages/go"
)

type row struct {
	ID      int    `json:"id"`
	Name    string `json:"name"`
	Payload string `json:"payload"`
	OK      bool   `json:"ok"`
}

func makeRows(n int) []row {
	items := make([]row, n)
	pay := string(bytes.Repeat([]byte("x"), 200))
	for i := range items {
		items[i] = row{ID: i, Name: "row", Payload: pay, OK: i%2 == 0}
	}
	return items
}

// peakHeapDuring runs f while sampling HeapAlloc on a goroutine, returning the
// peak observed above the pre-run baseline.
func peakHeapDuring(f func()) uint64 {
	runtime.GC()
	var base runtime.MemStats
	runtime.ReadMemStats(&base)

	var peak uint64
	stop := make(chan struct{})
	done := make(chan struct{})
	go func() {
		var m runtime.MemStats
		for {
			select {
			case <-stop:
				close(done)
				return
			default:
				runtime.ReadMemStats(&m)
				for {
					p := atomic.LoadUint64(&peak)
					if m.HeapAlloc <= p {
						break
					}
					if atomic.CompareAndSwapUint64(&peak, p, m.HeapAlloc) {
						break
					}
				}
				time.Sleep(200 * time.Microsecond)
			}
		}
	}()
	f()
	var after runtime.MemStats
	runtime.ReadMemStats(&after)
	if after.HeapAlloc > atomic.LoadUint64(&peak) {
		atomic.StoreUint64(&peak, after.HeapAlloc)
	}
	close(stop)
	<-done
	if peak < base.HeapAlloc {
		return 0
	}
	return peak - base.HeapAlloc
}

func median(f func(), iters int) float64 {
	f()
	s := make([]float64, iters)
	for i := 0; i < iters; i++ {
		t0 := time.Now()
		f()
		s[i] = time.Since(t0).Seconds()
	}
	for i := range s {
		for j := i + 1; j < len(s); j++ {
			if s[j] < s[i] {
				s[i], s[j] = s[j], s[i]
			}
		}
	}
	return s[len(s)/2]
}

func human(n uint64) string {
	units := []string{"B", "KB", "MB", "GB"}
	v := float64(n)
	i := 0
	for v >= 1024 && i < len(units)-1 {
		v /= 1024
		i++
	}
	if i == 0 {
		return fmt.Sprintf("%.0f%s", v, units[i])
	}
	return fmt.Sprintf("%.1f%s", v, units[i])
}

func main() {
	fmt.Println("Go benchmark: encoding/json materialized vs flatwire streaming")
	fmt.Print("(peak live heap via runtime.ReadMemStats; not cumulative -benchmem)\n\n")
	fmt.Printf("%9s %9s | %12s %12s | %12s %12s\n",
		"elements", "payload", "enc whole", "enc stream", "agg whole", "agg stream")
	fmt.Println("----------------------------------------------------------------------------")

	for _, n := range []int{1000, 10000, 50000} {
		items := makeRows(n)
		blob, _ := json.Marshal(items)
		size := len(blob)

		encWhole := peakHeapDuring(func() {
			b, _ := json.Marshal(items)
			_ = b
		})
		encStream := peakHeapDuring(func() {
			_, _ = flatwire.EncodeArray(items, io.Discard)
		})
		aggWhole := peakHeapDuring(func() {
			var all []row
			_ = json.Unmarshal(blob, &all)
			t := 0
			for _, r := range all {
				t += r.ID
			}
			_ = t
		})
		aggStream := peakHeapDuring(func() {
			t := 0
			_ = flatwire.DecodeArray(bytes.NewReader(blob), func(raw json.RawMessage) error {
				var r row
				if err := json.Unmarshal(raw, &r); err != nil {
					return err
				}
				t += r.ID
				return nil
			})
			_ = t
		})

		fmt.Printf("%9d %9s | %12s %12s | %12s %12s\n",
			n, human(uint64(size)), human(encWhole), human(encStream), human(aggWhole), human(aggStream))

		if n == 50000 {
			ew := median(func() { b, _ := json.Marshal(items); _ = b }, 5)
			es := median(func() { _, _ = flatwire.EncodeArray(items, io.Discard) }, 5)
			aw := median(func() {
				var all []row
				_ = json.Unmarshal(blob, &all)
				t := 0
				for _, r := range all {
					t += r.ID
				}
				_ = t
			}, 5)
			as := median(func() {
				t := 0
				_ = flatwire.DecodeArray(bytes.NewReader(blob), func(raw json.RawMessage) error {
					var r row
					_ = json.Unmarshal(raw, &r)
					t += r.ID
					return nil
				})
				_ = t
			}, 5)
			fmt.Printf("\ntime @50k (s): enc_whole=%.4f enc_stream=%.4f agg_whole=%.4f agg_stream=%.4f\n", ew, es, aw, as)
		}
	}
}
