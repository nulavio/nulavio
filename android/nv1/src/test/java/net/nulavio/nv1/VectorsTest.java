package net.nulavio.nv1;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import org.junit.BeforeClass;
import org.junit.Test;

/** Java against the desktop's libsodium: tests/fixtures/nv1-vectors.json (tests/lib/nv1_vectors.py). */
@SuppressWarnings("unchecked")
public class VectorsTest {
    static Map<String, Object> v;

    @BeforeClass
    public static void load() throws Exception {
        Path file = Path.of(System.getProperty("nv1.fixtures"), "nv1-vectors.json");
        v = Json.parseObject(Files.readAllBytes(file));
    }

    static Map<String, Object> m(String key) {
        return (Map<String, Object>) v.get(key);
    }

    static byte[] b(Map<String, Object> map, String key) {
        return B64.decode((String) map.get(key));
    }

    static Object[] parts(List<Object> raw, boolean strings) {
        return raw.stream().map(p -> {
            String s = (String) p;
            return s.startsWith("invite") || s.startsWith("Pixel") ? s : (Object) B64.decode(s);
        }).toArray();
    }

    @Test
    public void canonicalJsonMatchesPython() {
        Map<String, Object> c = m("canonical");
        assertEquals(c.get("bytes"), new String(Json.canonical(c.get("object")), StandardCharsets.US_ASCII));
    }

    @Test
    public void digitsAndEscapesStayAsciiInEveryLocale() {
        // Persian, Arabic, Devanagari and Thai digits: a phone in these languages must show and hash the same text.
        Locale saved = Locale.getDefault();
        try {
            for (String tag : new String[] {"fa-IR", "ar-EG", "hi-IN-u-nu-deva", "th-TH-u-nu-thai"}) {
                Locale.setDefault(Locale.forLanguageTag(tag));
                Map<String, Object> s = m("sas");
                assertEquals(tag, s.get("digits"), Nv1.sasDigits(b(s, "shared"), b(s, "t")));
                Map<String, Object> c = m("canonical");
                assertEquals(tag, c.get("bytes"), new String(Json.canonical(c.get("object")), StandardCharsets.US_ASCII));
            }
        } finally {
            Locale.setDefault(saved);
        }
    }

    @Test
    public void hashesAndKdf() {
        assertArrayEquals(b(m("hash32"), "out"), Crypto.hash32(b(m("hash32"), "message")));
        Map<String, Object> k = m("kdf");
        assertArrayEquals(b(k, "out"), Nv1.kdf(b(k, "key"), (String) k.get("label"), parts((List<Object>) k.get("parts"), true)));
        Map<String, Object> t = m("transcript");
        assertArrayEquals(b(t, "out"), Nv1.transcript(parts((List<Object>) t.get("parts"), true)));
        Map<String, Object> s = m("sas");
        assertEquals(s.get("digits"), Nv1.sasDigits(b(s, "shared"), b(s, "t")));
        Map<String, Object> pk = m("phone_kek");
        assertArrayEquals(b(pk, "out"), Nv1.phoneKek(b(pk, "z"), (String) pk.get("profile_id"),
                (String) pk.get("envelope_id"), (String) pk.get("phone_id"), b(pk, "eph_pk")));
        Map<String, Object> rk = m("response_key");
        assertArrayEquals(b(rk, "out"), Nv1.responseKey(b(rk, "shared"), b(rk, "request_hash")));
        Map<String, Object> ids = m("ids");
        assertEquals(ids.get("id"), Nv1.idFor(b(ids, "pk")));
        for (Object entry : (List<Object>) v.get("instance_names")) {
            List<Object> e = (List<Object>) entry;
            assertEquals(e.get(2), Link.instanceName((String) e.get(0), (String) e.get(1)));
        }
    }

    @Test
    public void x25519MatchesAndRefusesLowOrderPoints() {
        Map<String, Object> x = m("x25519");
        assertArrayEquals(b(x, "shared"), Crypto.x25519(b(x, "sk"), b(x, "pk")));
        assertArrayEquals(b(x, "public_of_sk"), Crypto.x25519Public(b(x, "sk")));
        try {
            Crypto.x25519(b(x, "sk"), new byte[32]);
            fail("an all-zero shared secret must be refused");
        } catch (PhoneRejected e) {
            assertEquals("bad-key", e.code);
        }
    }

    @Test
    public void ed25519SignaturesAreTheSame() {
        Map<String, Object> e = m("ed25519");
        assertArrayEquals(b(e, "pk"), Crypto.ed25519Public(b(e, "seed")));
        assertArrayEquals(b(e, "signature"), Crypto.sign(b(e, "seed"), b(e, "message")));
        assertTrue(Crypto.verify(b(e, "pk"), b(e, "message"), b(e, "signature")));
        byte[] tampered = b(e, "message");
        tampered[0] ^= 1;
        assertFalse(Crypto.verify(b(e, "pk"), tampered, b(e, "signature")));
    }

    @Test
    public void aeadInteroperates() {
        Map<String, Object> a = m("aead");
        assertArrayEquals(b(a, "ciphertext"), Crypto.aeadEncrypt(b(a, "key"), b(a, "nonce"), b(a, "plaintext"), b(a, "ad")));
        assertArrayEquals(b(a, "plaintext"), Crypto.aeadDecrypt(b(a, "key"), b(a, "nonce"), b(a, "ciphertext"), b(a, "ad")));
        try {
            Crypto.aeadDecrypt(b(a, "key"), b(a, "nonce"), b(a, "ciphertext"), "other".getBytes(StandardCharsets.US_ASCII));
            fail("wrong associated data must fail");
        } catch (PhoneRejected e) {
            assertEquals("bad-message", e.code);
        }
    }
}
