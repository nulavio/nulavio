package net.nulavio.nv1;

import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.Map;

/** Protocol nv1 helpers, byte for byte as the desktop's launcher/nulavio_launcher/vault/phone.py. */
public final class Nv1 {
    public static final byte[] CONTEXT = "nulavio/nv1/".getBytes(StandardCharsets.US_ASCII);
    public static final long CLOCK_SKEW = 120;

    private Nv1() {}

    static byte[] bytesOf(Object part) {
        if (part instanceof byte[]) {
            return (byte[]) part;
        }
        if (part instanceof String) {
            return ((String) part).getBytes(StandardCharsets.UTF_8);
        }
        throw new IllegalArgumentException("part must be bytes or a string");
    }

    private static void lengthPrefixed(ByteArrayOutputStream out, Object... parts) {
        for (Object part : parts) {
            byte[] data = bytesOf(part);
            int n = data.length;
            out.write(n >>> 24);
            out.write(n >>> 16);
            out.write(n >>> 8);
            out.write(n);
            out.write(data, 0, n);
        }
    }

    /** BLAKE2b keyed with {@code key} over CONTEXT ‖ label ‖ 0x00 ‖ length-prefixed parts. */
    public static byte[] kdf(byte[] key, String label, Object... parts) {
        ByteArrayOutputStream message = new ByteArrayOutputStream();
        message.write(CONTEXT, 0, CONTEXT.length);
        byte[] l = label.getBytes(StandardCharsets.US_ASCII);
        message.write(l, 0, l.length);
        message.write(0);
        lengthPrefixed(message, parts);
        return Crypto.blake2b(key, message.toByteArray());
    }

    /** BLAKE2b-256 over length-prefixed parts. */
    public static byte[] transcript(Object... parts) {
        ByteArrayOutputStream message = new ByteArrayOutputStream();
        lengthPrefixed(message, parts);
        return Crypto.hash32(message.toByteArray());
    }

    public static Map<String, Object> seal(byte[] key, byte[] plaintext, byte[] ad) {
        byte[] nonce = Crypto.random(Crypto.NONCE_BYTES);
        Map<String, Object> box = new LinkedHashMap<>();
        box.put("n", B64.encode(nonce));
        box.put("c", B64.encode(Crypto.aeadEncrypt(key, nonce, plaintext, ad)));
        return box;
    }

    public static byte[] unseal(byte[] key, Object box, byte[] ad) {
        if (!(box instanceof Map)) {
            throw new PhoneRejected("bad-message");
        }
        Map<?, ?> m = (Map<?, ?>) box;
        if (!(m.get("n") instanceof String) || !(m.get("c") instanceof String)) {
            throw new PhoneRejected("bad-message");
        }
        return Crypto.aeadDecrypt(key, B64.decode((String) m.get("n")), B64.decode((String) m.get("c")), ad);
    }

    public static Map<String, Object> sealJson(byte[] key, Map<String, Object> obj, byte[] ad) {
        return seal(key, Json.canonical(obj), ad);
    }

    public static Map<String, Object> unsealJson(byte[] key, Object box, byte[] ad) {
        byte[] plain = unseal(key, box, ad);
        try {
            return Json.parseObject(plain);
        } finally {
            Crypto.wipe(plain);
        }
    }

    public static String idFor(byte[] signingKey) {
        byte[] h = Crypto.hash32(signingKey);
        byte[] first = new byte[16];
        System.arraycopy(h, 0, first, 0, 16);
        return B64.encode(first);
    }

    public static String sasDigits(byte[] shared, byte[] t) {
        byte[] raw = kdf(shared, "pair/sas", t);
        long n = ((raw[0] & 0xffL) << 24) | ((raw[1] & 0xffL) << 16) | ((raw[2] & 0xffL) << 8) | (raw[3] & 0xffL);
        Crypto.wipe(raw);
        return String.format("%06d", n % 1_000_000L);
    }

    public static byte[] phoneKek(byte[] z, String profileId, String envelopeId, String phoneId, byte[] ephPk) {
        return kdf(z, "envelope/phone", profileId, envelopeId, phoneId, ephPk);
    }

    public static byte[] responseKey(byte[] shared, byte[] requestHash) {
        return kdf(shared, "unlock/response", requestHash);
    }

    public static byte[] concat(byte[]... parts) {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        for (byte[] p : parts) {
            out.write(p, 0, p.length);
        }
        return out.toByteArray();
    }

    public static byte[] ascii(String s) {
        return s.getBytes(StandardCharsets.US_ASCII);
    }

    public static byte[] requestSigningInput(Map<String, Object> request) {
        return concat(ascii("nv1/unlock/request"), Json.canonical(request));
    }

    public static byte[] responseSigningInput(byte[] requestHash, Map<String, Object> payload) {
        return concat(ascii("nv1/unlock/response"), requestHash, Json.canonical(payload));
    }
}
