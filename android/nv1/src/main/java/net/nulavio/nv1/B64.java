package net.nulavio.nv1;

import java.util.Base64;

/** URL-safe Base64 without padding, as the desktop writes it (vault/core.py b64e/b64d). */
public final class B64 {
    private B64() {}

    public static String encode(byte[] data) {
        return Base64.getUrlEncoder().withoutPadding().encodeToString(data);
    }

    public static byte[] decode(String text) {
        try {
            return Base64.getUrlDecoder().decode(text);
        } catch (IllegalArgumentException e) {
            throw new PhoneRejected("bad-message");
        }
    }
}
