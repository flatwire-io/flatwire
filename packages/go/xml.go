package flatwire

// Streaming XML format for flatwire, mirroring the JSON path and the Python/JS
// reference. XML has no native types, so flatwire uses an explicit, typed,
// fully round-trippable convention (see docs/FORMATS.md):
//
//	42        -> <item type="int">42</item>
//	"hi"      -> <item type="str">hi</item>
//	true      -> <item type="bool">true</item>
//	null      -> <item type="null"/>
//	{"id":1}  -> <item type="object"><f k="id" type="int">1</f></item>
//	[1,2]     -> <item type="array"><e type="int">1</e><e type="int">2</e></item>
//
// Values are Go's generic any (objects -> map[string]any, arrays -> []any,
// scalars -> int64/float64/bool/string/nil). Encoding writes one <item> at a
// time; decoding uses encoding/xml's streaming token reader and builds one
// element subtree at a time, so peak memory stays bounded by the largest element.

import (
	"encoding/xml"
	"fmt"
	"io"
	"strconv"
	"strings"
)

func xmlType(v any) string {
	switch v.(type) {
	case nil:
		return "null"
	case bool:
		return "bool"
	case int, int8, int16, int32, int64, uint, uint8, uint16, uint32, uint64:
		return "int"
	case float32, float64:
		return "float"
	case string:
		return "str"
	case map[string]any:
		return "object"
	case []any:
		return "array"
	default:
		return ""
	}
}

func escapeXMLText(s string) string {
	r := strings.NewReplacer("&", "&amp;", "<", "&lt;", ">", "&gt;")
	return r.Replace(s)
}

func escapeXMLAttr(s string) string {
	r := strings.NewReplacer("&", "&amp;", "<", "&lt;", ">", "&gt;", "\"", "&quot;")
	return r.Replace(s)
}

func writeXMLValue(w io.Writer, tag, key string, v any) error {
	t := xmlType(v)
	if t == "" {
		return fmt.Errorf("flatwire xml: unsupported type %T", v)
	}
	keyAttr := ""
	if key != "" {
		keyAttr = fmt.Sprintf(" k=%q", escapeXMLAttr(key))
	}
	switch t {
	case "null":
		_, err := fmt.Fprintf(w, "<%s%s type=\"null\"/>", tag, keyAttr)
		return err
	case "object":
		if _, err := fmt.Fprintf(w, "<%s%s type=\"object\">", tag, keyAttr); err != nil {
			return err
		}
		for k, val := range v.(map[string]any) {
			if err := writeXMLValue(w, "f", k, val); err != nil {
				return err
			}
		}
		_, err := fmt.Fprintf(w, "</%s>", tag)
		return err
	case "array":
		if _, err := fmt.Fprintf(w, "<%s%s type=\"array\">", tag, keyAttr); err != nil {
			return err
		}
		for _, e := range v.([]any) {
			if err := writeXMLValue(w, "e", "", e); err != nil {
				return err
			}
		}
		_, err := fmt.Fprintf(w, "</%s>", tag)
		return err
	case "bool":
		s := "false"
		if v.(bool) {
			s = "true"
		}
		_, err := fmt.Fprintf(w, "<%s%s type=\"bool\">%s</%s>", tag, keyAttr, s, tag)
		return err
	default: // int, float, str
		var text string
		switch n := v.(type) {
		case string:
			text = escapeXMLText(n)
		default:
			text = escapeXMLText(fmt.Sprintf("%v", n))
		}
		_, err := fmt.Fprintf(w, "<%s%s type=%q>%s</%s>", tag, keyAttr, t, text, tag)
		return err
	}
}

// EncodeArrayXML streams a collection as <root> containing one <item> per
// element. Peak memory is bounded by the largest single element. Returns count.
func EncodeArrayXML(items []any, w io.Writer, root string) (int, error) {
	if root == "" {
		root = "items"
	}
	if _, err := fmt.Fprintf(w, "<?xml version=\"1.0\" encoding=\"UTF-8\"?><%s>", root); err != nil {
		return 0, err
	}
	count := 0
	for _, v := range items {
		if err := writeXMLValue(w, "item", "", v); err != nil {
			return count, err
		}
		count++
	}
	_, err := fmt.Fprintf(w, "</%s>", root)
	return count, err
}

// DecodeArrayXML lazily reads a streamed XML collection, calling yield with each
// decoded element in turn. Backed by encoding/xml's streaming token reader, so
// the whole document is never held in memory at once.
func DecodeArrayXML(r io.Reader, item string, yield func(any) error) error {
	if item == "" {
		item = "item"
	}
	dec := xml.NewDecoder(r)
	// Advance to the root start element.
	if _, err := nextStart(dec); err != nil {
		return err
	}
	for {
		tok, err := dec.Token()
		if err == io.EOF {
			return nil
		}
		if err != nil {
			return err
		}
		switch t := tok.(type) {
		case xml.StartElement:
			if t.Name.Local == item {
				v, err := readXMLValue(dec, t)
				if err != nil {
					return err
				}
				if err := yield(v); err != nil {
					return err
				}
			}
		case xml.EndElement:
			// root end -> done
			return drain(dec)
		}
	}
}

func nextStart(dec *xml.Decoder) (xml.StartElement, error) {
	for {
		tok, err := dec.Token()
		if err != nil {
			return xml.StartElement{}, err
		}
		if se, ok := tok.(xml.StartElement); ok {
			return se, nil
		}
	}
}

func drain(dec *xml.Decoder) error {
	for {
		_, err := dec.Token()
		if err == io.EOF {
			return nil
		}
		if err != nil {
			return err
		}
	}
}

func attr(se xml.StartElement, name string) string {
	for _, a := range se.Attr {
		if a.Name.Local == name {
			return a.Value
		}
	}
	return ""
}

// readXMLValue reads the content of the element whose StartElement is `se`,
// consuming up to and including its EndElement.
func readXMLValue(dec *xml.Decoder, se xml.StartElement) (any, error) {
	t := attr(se, "type")
	switch t {
	case "null":
		return nil, skipElement(dec)
	case "object":
		obj := map[string]any{}
		for {
			tok, err := dec.Token()
			if err != nil {
				return nil, err
			}
			switch tk := tok.(type) {
			case xml.StartElement:
				k := attr(tk, "k")
				v, err := readXMLValue(dec, tk)
				if err != nil {
					return nil, err
				}
				obj[k] = v
			case xml.EndElement:
				return obj, nil
			}
		}
	case "array":
		arr := []any{}
		for {
			tok, err := dec.Token()
			if err != nil {
				return nil, err
			}
			switch tk := tok.(type) {
			case xml.StartElement:
				v, err := readXMLValue(dec, tk)
				if err != nil {
					return nil, err
				}
				arr = append(arr, v)
			case xml.EndElement:
				return arr, nil
			}
		}
	default: // scalar
		var text strings.Builder
		for {
			tok, err := dec.Token()
			if err != nil {
				return nil, err
			}
			switch tk := tok.(type) {
			case xml.CharData:
				text.Write(tk)
			case xml.EndElement:
				return parseScalar(t, text.String()), nil
			}
		}
	}
}

func skipElement(dec *xml.Decoder) error {
	depth := 0
	for {
		tok, err := dec.Token()
		if err != nil {
			return err
		}
		switch tok.(type) {
		case xml.StartElement:
			depth++
		case xml.EndElement:
			if depth == 0 {
				return nil
			}
			depth--
		}
	}
}

func parseScalar(t, raw string) any {
	switch t {
	case "int":
		n, _ := strconv.ParseInt(raw, 10, 64)
		return n
	case "float":
		f, _ := strconv.ParseFloat(raw, 64)
		return f
	case "bool":
		return raw == "true"
	default:
		return raw
	}
}
