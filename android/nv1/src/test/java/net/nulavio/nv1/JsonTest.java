package net.nulavio.nv1;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.fail;

import java.nio.charset.StandardCharsets;
import java.util.Map;
import org.junit.Test;

public class JsonTest {
    @Test
    public void roundTripKeepsTheCanonicalBytes() {
        String text = "{\"b\":[1,-2,{\"x\":null}],\"a\":\"\\u00e9\\ud83d\\ude00\",\"c\":true}";
        Map<String, Object> obj = Json.parseObject(text);
        assertEquals("{\"a\":\"\\u00e9\\ud83d\\ude00\",\"b\":[1,-2,{\"x\":null}],\"c\":true}",
                new String(Json.canonical(obj), StandardCharsets.US_ASCII));
    }

    @Test
    public void refusesWhatNv1NeverSends() {
        for (String bad : new String[] {"[1]", "{\"a\":1.5}", "{\"a\":1} x", "{\"a\":\"\u0001\"}", "{\"a\":", "",
                "{\"a\":99999999999999999999}", "[".repeat(40) + "]".repeat(40)}) {
            try {
                Json.parseObject(bad);
                fail("accepted: " + bad);
            } catch (PhoneRejected e) {
                assertEquals("bad-message", e.code);
            }
        }
    }
}
