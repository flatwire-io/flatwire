package flatwire

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
)

// StreamError is returned by DecodeCheckedArray when the producer finished the
// stream with "complete":false. Err holds the raw error payload from the wire.
type StreamError struct {
	Err json.RawMessage
}

func (e *StreamError) Error() string {
	return "flatwire: producer signalled stream failure: " + string(e.Err)
}

// TruncatedStreamError is returned when the stream ended before a terminal
// status was written (dropped connection, crashed producer).
type TruncatedStreamError struct {
	msg string
}

func (e *TruncatedStreamError) Error() string { return "flatwire: " + e.msg }

// EncodeCheckedArray streams items inside a checked envelope, writing the
// terminal status LAST, matching the Python/Node reference:
//
//	{"items":[ e0, e1, ... ],"complete":true}
//	{"items":[ e0, e1, ... ],"complete":false,"error":{"message":"...","type":"..."}}
//
// so a consumer can tell clean completion, an in-band producer error after N
// rows, and truncation apart. If encoding an element fails, a complete:false
// trailer carrying the error is written before the error is returned. Returns
// the number of elements written. The wire is plain JSON and interoperates with
// every other flatwire language. See docs/FAILURE.md.
func EncodeCheckedArray[T any](items []T, w io.Writer) (int, error) {
	if _, err := io.WriteString(w, `{"items":[`); err != nil {
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
			errObj := map[string]string{"message": err.Error(), "type": "EncodeError"}
			eb, _ := json.Marshal(errObj)
			io.WriteString(w, `],"complete":false,"error":`)
			w.Write(eb)
			io.WriteString(w, "}")
			return count, err
		}
		if _, err := w.Write(bytes.TrimRight(buf.Bytes(), "\n")); err != nil {
			return count, err
		}
		count++
	}
	if _, err := io.WriteString(w, `],"complete":true}`); err != nil {
		return count, err
	}
	return count, nil
}

// DecodeCheckedArray lazily reads a checked envelope from r, handing each element
// to yield in turn (one at a time, so peak memory stays flat), then enforces the
// terminal status. It returns a *StreamError if the producer signalled
// complete:false, a *TruncatedStreamError if the stream ended before a terminal
// status, or a plain error for malformed input. A clean stream returns nil.
// Returning a non-nil error from yield stops iteration and is returned as-is.
func DecodeCheckedArray(r io.Reader, yield func(json.RawMessage) error) error {
	dec := json.NewDecoder(r)

	if err := expectDelim(dec, '{'); err != nil {
		return truncatedOr(err, "stream ended before items array")
	}
	key, err := dec.Token()
	if err != nil {
		return truncatedOr(err, "stream ended before items array")
	}
	if key != "items" {
		return errors.New("flatwire: DecodeCheckedArray expects a checked stream ({\"items\":[...]})")
	}
	if err := expectDelim(dec, '['); err != nil {
		return truncatedOr(err, "stream ended before items array")
	}

	for dec.More() {
		var raw json.RawMessage
		if err := dec.Decode(&raw); err != nil {
			return truncatedOr(err, "stream ended inside items array")
		}
		if err := yield(raw); err != nil {
			return err
		}
	}
	if _, err := dec.Token(); err != nil { // closing ']'
		return truncatedOr(err, "stream ended inside items array")
	}

	seenComplete := false
	complete := false
	var streamErr json.RawMessage
	for dec.More() {
		k, err := dec.Token()
		if err != nil {
			return truncatedOr(err, "stream ended before terminal status")
		}
		switch k {
		case "complete":
			v, err := dec.Token()
			if err != nil {
				return truncatedOr(err, "stream ended before terminal status")
			}
			b, _ := v.(bool)
			complete, seenComplete = b, true
		case "error":
			if err := dec.Decode(&streamErr); err != nil {
				return truncatedOr(err, "stream ended before terminal status")
			}
		default:
			var skip json.RawMessage
			if err := dec.Decode(&skip); err != nil {
				return truncatedOr(err, "stream ended before terminal status")
			}
		}
	}
	if _, err := dec.Token(); err != nil { // closing '}'
		return truncatedOr(err, "stream ended before terminal status")
	}

	if !seenComplete {
		return &TruncatedStreamError{msg: "stream ended before terminal status"}
	}
	if !complete {
		if streamErr == nil {
			streamErr = json.RawMessage(`"unknown stream error"`)
		}
		return &StreamError{Err: streamErr}
	}
	return nil
}

func expectDelim(dec *json.Decoder, want json.Delim) error {
	tok, err := dec.Token()
	if err != nil {
		return err
	}
	if d, ok := tok.(json.Delim); !ok || d != want {
		return errors.New("flatwire: unexpected token, not a checked stream")
	}
	return nil
}

func truncatedOr(err error, msg string) error {
	if errors.Is(err, io.EOF) || errors.Is(err, io.ErrUnexpectedEOF) {
		return &TruncatedStreamError{msg: msg}
	}
	return err
}
