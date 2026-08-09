// flatwire conformance runner (Go). Encodes+decodes every corpus case in every
// format, records round-trip and a SHA-256 of the encoded bytes -> results/go.json.
package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"reflect"

	flatwire "github.com/flatwire-io/flatwire/packages/go"
)

func corpusRoot() string {
	dir, _ := os.Getwd()
	for {
		if _, err := os.Stat(filepath.Join(dir, "corpus.json")); err == nil {
			return dir
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			panic("could not locate corpus.json")
		}
		dir = parent
	}
}

// toModel converts a json.RawMessage-decoded value (using json.Number) into the
// canonical model: map[string]any, []any, int64/float64/bool/string/nil.
func toModel(v any) any {
	switch x := v.(type) {
	case json.Number:
		if i, err := x.Int64(); err == nil {
			return i
		}
		f, _ := x.Float64()
		return f
	case map[string]any:
		m := make(map[string]any, len(x))
		for k, val := range x {
			m[k] = toModel(val)
		}
		return m
	case []any:
		a := make([]any, len(x))
		for i, e := range x {
			a[i] = toModel(e)
		}
		return a
	default:
		return x
	}
}

func decodeJSONValue(data []byte) (any, error) {
	dec := json.NewDecoder(bytes.NewReader(data))
	dec.UseNumber()
	var v any
	if err := dec.Decode(&v); err != nil {
		return nil, err
	}
	return toModel(v), nil
}

func encode(elements []any, fmtName string) ([]byte, error) {
	var buf bytes.Buffer
	var err error
	switch fmtName {
	case "json":
		_, err = flatwire.EncodeArray(elements, &buf)
	case "xml":
		_, err = flatwire.EncodeArrayXML(elements, &buf, "items")
	case "msgpack":
		_, err = flatwire.EncodeArrayMsgPack(elements, &buf)
	}
	return buf.Bytes(), err
}

func decode(data []byte, fmtName string) ([]any, error) {
	var out []any
	var err error
	switch fmtName {
	case "json":
		err = flatwire.DecodeArray(bytes.NewReader(data), func(raw json.RawMessage) error {
			v, e := decodeJSONValue(raw)
			if e != nil {
				return e
			}
			out = append(out, v)
			return nil
		})
	case "xml":
		err = flatwire.DecodeArrayXML(bytes.NewReader(data), "item", func(v any) error {
			out = append(out, v)
			return nil
		})
	case "msgpack":
		err = flatwire.DecodeArrayMsgPack(bytes.NewReader(data), func(v any) error {
			out = append(out, v)
			return nil
		})
	}
	if out == nil {
		out = []any{}
	}
	return out, err
}

// modelEqual compares two model values with int/float numeric tolerance.
func modelEqual(a, b any) bool {
	an, aok := toFloat(a)
	bn, bok := toFloat(b)
	if aok && bok {
		return an == bn || (math.IsNaN(an) && math.IsNaN(bn))
	}
	switch ax := a.(type) {
	case map[string]any:
		bx, ok := b.(map[string]any)
		if !ok || len(ax) != len(bx) {
			return false
		}
		for k, av := range ax {
			bv, ok := bx[k]
			if !ok || !modelEqual(av, bv) {
				return false
			}
		}
		return true
	case []any:
		bx, ok := b.([]any)
		if !ok || len(ax) != len(bx) {
			return false
		}
		for i := range ax {
			if !modelEqual(ax[i], bx[i]) {
				return false
			}
		}
		return true
	default:
		return reflect.DeepEqual(a, b)
	}
}

func toFloat(v any) (float64, bool) {
	switch x := v.(type) {
	case int64:
		return float64(x), true
	case int:
		return float64(x), true
	case uint64:
		return float64(x), true
	case float64:
		return x, true
	default:
		return 0, false
	}
}

func main() {
	root := corpusRoot()
	raw, _ := os.ReadFile(filepath.Join(root, "corpus.json"))
	var corpus struct {
		Cases []struct {
			Name     string          `json:"name"`
			Tier     string          `json:"tier"`
			Elements json.RawMessage `json:"elements"`
		} `json:"cases"`
	}
	if err := json.Unmarshal(raw, &corpus); err != nil {
		panic(err)
	}

	formats := []string{"json", "xml", "msgpack"}
	cases := map[string]any{}
	passed, total := 0, 0

	for _, c := range corpus.Cases {
		// Parse elements with UseNumber to preserve int vs float.
		dec := json.NewDecoder(bytes.NewReader(c.Elements))
		dec.UseNumber()
		var rawElems []any
		_ = dec.Decode(&rawElems)
		elements := make([]any, len(rawElems))
		for i, e := range rawElems {
			elements[i] = toModel(e)
		}

		fmtResults := map[string]any{}
		for _, f := range formats {
			total++
			data, err := encode(elements, f)
			if err != nil {
				fmtResults[f] = map[string]any{"roundtrip": false, "error": err.Error()}
				continue
			}
			out, err := decode(data, f)
			if err != nil {
				fmtResults[f] = map[string]any{"roundtrip": false, "error": err.Error()}
				continue
			}
			rt := len(out) == len(elements)
			if rt {
				for i := range elements {
					if !modelEqual(elements[i], out[i]) {
						rt = false
						break
					}
				}
			}
			if rt {
				passed++
			}
			sum := sha256.Sum256(data)
			fmtResults[f] = map[string]any{
				"roundtrip": rt,
				"sha256":    fmt.Sprintf("%x", sum),
				"bytes":     len(data),
			}
		}
		cases[c.Name] = map[string]any{"tier": c.Tier, "formats": fmtResults}
	}

	results := map[string]any{"lang": "go", "tested_locally": true, "cases": cases}
	outPath := filepath.Join(root, "results", "go.json")
	_ = os.MkdirAll(filepath.Dir(outPath), 0o755)
	b, _ := json.MarshalIndent(results, "", "  ")
	_ = os.WriteFile(outPath, b, 0o644)
	fmt.Printf("go conformance: %d/%d round-trip; wrote %s\n", passed, total, outPath)
}
