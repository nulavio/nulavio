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

    @Test
    public void numbersAndEscapesFollowTheJsonGrammar() {
        // #676: a minus sign without a digit reached Long.parseLong and crashed the scan.
        for (String bad : new String[] {"{\"v\":-}", "{\"v\":-x}", "{\"v\":--1}", "{\"v\":01}", "{\"v\":-01}",
                "{\"v\":\u0661}", "{\"v\":1e3}", "{\"v\":+1}", "{\"v\":\"\\u-001\"}", "{\"v\":\"\\u+041\"}"}) {
            try {
                Json.parseObject(bad);
                fail("accepted: " + bad);
            } catch (PhoneRejected e) {
                assertEquals("bad-message", e.code);
            }
        }
        Map<String, Object> obj = Json.parseObject("{\"a\":0,\"b\":-0,\"c\":-12,\"d\":907,\"e\":\"\\u00E9\"}");
        assertEquals(0L, obj.get("a"));
        assertEquals(0L, obj.get("b"));
        assertEquals(-12L, obj.get("c"));
        assertEquals(907L, obj.get("d"));
        assertEquals("\u00e9", obj.get("e"));
    }

    @Test
    public void theLengthLimitCountsTheMinusSign() {
        // A number is at most 18 characters, sign included, as before the grammar check.
        String digits18 = "9".repeat(18);
        for (String bad : new String[] {"{\"v\":-" + digits18 + "}", "{\"v\":1" + digits18 + "}"}) {
            try {
                Json.parseObject(bad);
                fail("accepted: " + bad);
            } catch (PhoneRejected e) {
                assertEquals("bad-message", e.code);
            }
        }
        Map<String, Object> obj = Json.parseObject("{\"a\":" + digits18 + ",\"b\":-" + "9".repeat(17) + "}");
        assertEquals(999999999999999999L, obj.get("a"));
        assertEquals(-99999999999999999L, obj.get("b"));
    }
}
