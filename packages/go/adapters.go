package flatwire

// Framework adapter for Go's net/http. The adoption moment isn't
// EncodeArray(items, w) — it's returning a streamed, flat-memory response in one
// line from an HTTP handler, with the right Content-Type set for you.
//
// WriteArray sets the Content-Type from the format, streams the collection
// element-by-element straight to the ResponseWriter (peak memory bounded by the
// largest single element), flushes if the writer supports it, and returns the
// element count:
//
//	func rows(w http.ResponseWriter, r *http.Request) {
//	    _, _ = flatwire.WriteArray(w, getRows(), "cbor")   // flat memory
//	}
//
// ArrayHandler wraps that as an http.Handler for one-line route registration:
//
//	mux.Handle("/rows", flatwire.ArrayHandler(getRows(), "json"))

import (
	"fmt"
	"net/http"
)

// MediaTypes maps a flatwire format name to its HTTP Content-Type.
var MediaTypes = map[string]string{
	"json":    "application/json",
	"xml":     "application/xml",
	"msgpack": "application/msgpack",
	"cbor":    "application/cbor",
}

// WriteArray streams items to an http.ResponseWriter in the given format
// (json/xml/msgpack/cbor), setting the Content-Type header first and flushing at
// the end when the writer supports http.Flusher. Peak memory stays bounded by the
// largest single element. Returns the number of elements written.
//
// Note: set any additional headers and the status code before calling WriteArray
// — writing the body commits the header block.
func WriteArray(w http.ResponseWriter, items []any, format string) (int, error) {
	ct, ok := MediaTypes[format]
	if !ok {
		return 0, fmt.Errorf("flatwire: unknown format %q (expected json, xml, msgpack, or cbor)", format)
	}
	if w.Header().Get("Content-Type") == "" {
		w.Header().Set("Content-Type", ct)
	}

	var n int
	var err error
	switch format {
	case "json":
		n, err = EncodeArray(items, w)
	case "xml":
		n, err = EncodeArrayXML(items, w, "items")
	case "msgpack":
		n, err = EncodeArrayMsgPack(items, w)
	case "cbor":
		n, err = EncodeArrayCBOR(items, w)
	}
	if f, ok := w.(http.Flusher); ok {
		f.Flush()
	}
	return n, err
}

// ArrayHandler returns an http.Handler that streams items in the given format on
// every request. Handy for a one-line route:
//
//	mux.Handle("/rows", flatwire.ArrayHandler(rows, "cbor"))
func ArrayHandler(items []any, format string) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if _, err := WriteArray(w, items, format); err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
		}
	})
}
