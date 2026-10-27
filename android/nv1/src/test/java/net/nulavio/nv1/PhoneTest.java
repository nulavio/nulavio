package net.nulavio.nv1;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

import java.util.Map;
import org.junit.Test;

/** What the phone keeps and refuses without a desktop (the protocol itself: test_companion_protocol.py). */
public class PhoneTest {
    @Test
    public void publicStateHoldsNoSecret() {
        Secrets secrets = Secrets.generate();
        Phone phone = Phone.create("Pixel", secrets, () -> 0L);
        String state = new String(Json.canonical(phone.toState()), java.nio.charset.StandardCharsets.US_ASCII);
        Map<String, Object> keys = secrets.toJson();
        assertFalse(state.contains((String) keys.get("sig_sk")));
        assertFalse(state.contains((String) keys.get("kx_sk")));
        assertFalse(phone.toState().containsKey("sig_sk") || phone.toState().containsKey("kx_sk"));
        Phone again = Phone.fromState(phone.toState(), () -> 0L);
        assertEquals(phone.phoneId(), again.phoneId());
        assertTrue(again.owns(Secrets.fromBytes(secrets.toBytes())));
        assertFalse(again.owns(Secrets.generate()));
    }

    @Test
    public void namesAreLimitedLikeTheDesktopDoes() {
        String longName = "x".repeat(70) + "😀";
        Phone phone = Phone.create(longName, Secrets.generate(), () -> 0L);
        assertEquals(64, phone.name().codePointCount(0, phone.name().length()));
    }

    @Test
    public void foreignSecretsAndUnknownDesktopsAreRefused() {
        Phone phone = Phone.create("Pixel", Secrets.generate(), () -> 0L);
        Map<String, Object> request = Json.parseObject("{\"r\":{\"desktop_id\":\"nobody\"},\"sig\":\"AA\"}");
        try {
            phone.check(request);
            fail();
        } catch (PhoneRejected e) {
            assertEquals("unpaired-desktop", e.code);
        }
        try {
            phone.answer(request, Phone.Answer.APPROVE, Secrets.generate());
            fail();
        } catch (PhoneRejected e) {
            assertEquals("bad-state", e.code);
        }
        assertEquals("unlock", Phone.kindOf(request));
        assertEquals("pair", Phone.kindOf(Json.parseObject("{\"v\":1,\"i\":\"a\",\"s\":\"b\"}")));
        assertEquals(null, Phone.kindOf(Json.parseObject("{\"v\":2}")));
    }
}
