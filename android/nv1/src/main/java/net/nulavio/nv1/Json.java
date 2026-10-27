package net.nulavio.nv1;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

/**
 * The JSON nv1 needs: objects, arrays, strings, integers, booleans, null.
 *
 * <p>{@link #canonical} writes exactly what the desktop's {@code json.dumps(obj, sort_keys=True,
 * separators=(",", ":"), ensure_ascii=True)} writes, because signatures and hashes cover those bytes.
 */
public final class Json {
    private Json() {}

    public static byte[] canonical(Object value) {
        StringBuilder out = new StringBuilder();
        write(out, value);
        return out.toString().getBytes(StandardCharsets.US_ASCII);
    }

    private static void write(StringBuilder out, Object value) {
        if (value == null) {
            out.append("null");
        } else if (value instanceof String) {
            writeString(out, (String) value);
        } else if (value instanceof Boolean) {
            out.append(((Boolean) value) ? "true" : "false");
        } else if (value instanceof Long || value instanceof Integer) {
            out.append(((Number) value).longValue());
        } else if (value instanceof Map) {
            TreeMap<String, Object> sorted = new TreeMap<>();
            for (Map.Entry<?, ?> e : ((Map<?, ?>) value).entrySet()) {
                sorted.put((String) e.getKey(), e.getValue());
            }
            out.append('{');
            boolean first = true;
            for (Map.Entry<String, Object> e : sorted.entrySet()) {
                if (!first) {
                    out.append(',');
                }
                first = false;
                writeString(out, e.getKey());
                out.append(':');
                write(out, e.getValue());
            }
            out.append('}');
        } else if (value instanceof List) {
            out.append('[');
            boolean first = true;
            for (Object item : (List<?>) value) {
                if (!first) {
                    out.append(',');
                }
                first = false;
                write(out, item);
            }
            out.append(']');
        } else {
            throw new IllegalArgumentException("not JSON: " + value.getClass());
        }
    }

    private static void writeString(StringBuilder out, String s) {
        out.append('"');
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"': out.append("\\\""); break;
                case '\\': out.append("\\\\"); break;
                case '\n': out.append("\\n"); break;
                case '\r': out.append("\\r"); break;
                case '\t': out.append("\\t"); break;
                case '\b': out.append("\\b"); break;
                case '\f': out.append("\\f"); break;
                default:
                    if (c < 0x20 || c > 0x7e) {
                        out.append(String.format("\\u%04x", (int) c)); // Python escapes DEL and every non-ASCII unit
                    } else {
                        out.append(c);
                    }
            }
        }
        out.append('"');
    }

    // -- parsing --------------------------------------------------------------------------

    public static Map<String, Object> parseObject(byte[] data) {
        return parseObject(new String(data, StandardCharsets.UTF_8));
    }

    @SuppressWarnings("unchecked")
    public static Map<String, Object> parseObject(String text) {
        Parser p = new Parser(text);
        Object value = p.value();
        p.skipSpace();
        if (p.pos != text.length() || !(value instanceof Map)) {
            throw new PhoneRejected("bad-message");
        }
        return (Map<String, Object>) value;
    }

    private static final class Parser {
        final String s;
        int pos;
        int depth;

        Parser(String s) {
            this.s = s;
        }

        void skipSpace() {
            while (pos < s.length() && " \t\r\n".indexOf(s.charAt(pos)) >= 0) {
                pos++;
            }
        }

        char peek() {
            if (pos >= s.length()) {
                throw new PhoneRejected("bad-message");
            }
            return s.charAt(pos);
        }

        void expect(char c) {
            if (peek() != c) {
                throw new PhoneRejected("bad-message");
            }
            pos++;
        }

        Object value() {
            skipSpace();
            if (++depth > 32) {
                throw new PhoneRejected("bad-message");
            }
            try {
                char c = peek();
                if (c == '{') {
                    return object();
                }
                if (c == '[') {
                    return array();
                }
                if (c == '"') {
                    return string();
                }
                if (s.startsWith("true", pos)) {
                    pos += 4;
                    return Boolean.TRUE;
                }
                if (s.startsWith("false", pos)) {
                    pos += 5;
                    return Boolean.FALSE;
                }
                if (s.startsWith("null", pos)) {
                    pos += 4;
                    return null;
                }
                return number();
            } finally {
                depth--;
            }
        }

        Map<String, Object> object() {
            expect('{');
            TreeMap<String, Object> out = new TreeMap<>();
            skipSpace();
            if (peek() == '}') {
                pos++;
                return out;
            }
            while (true) {
                skipSpace();
                String key = string();
                skipSpace();
                expect(':');
                out.put(key, value());
                skipSpace();
                if (peek() == ',') {
                    pos++;
                    continue;
                }
                expect('}');
                return out;
            }
        }

        List<Object> array() {
            expect('[');
            List<Object> out = new ArrayList<>();
            skipSpace();
            if (peek() == ']') {
                pos++;
                return out;
            }
            while (true) {
                out.add(value());
                skipSpace();
                if (peek() == ',') {
                    pos++;
                    continue;
                }
                expect(']');
                return out;
            }
        }

        String string() {
            expect('"');
            StringBuilder out = new StringBuilder();
            while (true) {
                char c = peek();
                pos++;
                if (c == '"') {
                    return out.toString();
                }
                if (c < 0x20) {
                    throw new PhoneRejected("bad-message");
                }
                if (c != '\\') {
                    out.append(c);
                    continue;
                }
                char e = peek();
                pos++;
                switch (e) {
                    case '"': out.append('"'); break;
                    case '\\': out.append('\\'); break;
                    case '/': out.append('/'); break;
                    case 'b': out.append('\b'); break;
                    case 'f': out.append('\f'); break;
                    case 'n': out.append('\n'); break;
                    case 'r': out.append('\r'); break;
                    case 't': out.append('\t'); break;
                    case 'u':
                        if (pos + 4 > s.length()) {
                            throw new PhoneRejected("bad-message");
                        }
                        try {
                            out.append((char) Integer.parseInt(s.substring(pos, pos + 4), 16));
                        } catch (NumberFormatException ex) {
                            throw new PhoneRejected("bad-message");
                        }
                        pos += 4;
                        break;
                    default:
                        throw new PhoneRejected("bad-message");
                }
            }
        }

        Long number() {
            int start = pos;
            if (pos < s.length() && s.charAt(pos) == '-') {
                pos++;
            }
            while (pos < s.length() && Character.isDigit(s.charAt(pos))) {
                pos++;
            }
            if (start == pos || pos - start > 18) {
                throw new PhoneRejected("bad-message"); // nv1 has only small integers
            }
            return Long.parseLong(s.substring(start, pos));
        }
    }
}
