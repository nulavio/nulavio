package net.nulavio.nv1;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

import java.util.Map;
import java.util.TreeMap;
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
        assertEquals("pair", Phone.kindOf(Json.parseObject("{\"v\":2,\"i\":\"a\",\"s\":\"b\"}")));
        assertEquals("pair", Phone.kindOf(Json.parseObject("{\"v\":1,\"i\":\"a\",\"s\":\"b\"}"))); // refused by scan
        assertEquals(null, Phone.kindOf(Json.parseObject("{\"v\":2}")));
    }

    @Test
    public void unlockRequestsWithoutAStringDesktopIdAreRefused() {
        // #676: a missing or non-String desktop_id reached the TreeMap lookup and crashed the scan.
        Secrets secrets = Secrets.generate();
        Map<String, Object> state = Phone.create("Pixel", secrets, () -> 0L).toState();
        Map<String, Object> paired = new TreeMap<>();
        paired.put("dsig_pk", B64.encode(Crypto.ed25519Keypair()[1]));
        paired.put("name", "Desktop");
        Map<String, Object> desktops = new TreeMap<>();
        desktops.put("some-desktop", paired);
        state.put("desktops", desktops);
        Phone phone = Phone.fromState(state, () -> 0L);
        for (String text : new String[] {"{\"r\":{},\"sig\":\"x\"}", "{\"r\":{\"desktop_id\":1},\"sig\":\"x\"}",
                "{\"r\":{\"desktop_id\":null},\"sig\":\"x\"}", "{\"r\":{\"desktop_id\":[\"a\"]},\"sig\":\"x\"}"}) {
            Map<String, Object> request = Json.parseObject(text);
            assertEquals("unlock", Phone.kindOf(request));
            try {
                phone.check(request);
                fail("check accepted: " + text);
            } catch (PhoneRejected e) {
                assertEquals("bad-message", e.code);
            }
            try {
                phone.answer(request, Phone.Answer.DECLINE, secrets);
                fail("answer accepted: " + text);
            } catch (PhoneRejected e) {
                assertEquals("bad-message", e.code);
            }
        }
    }

    @Test
    public void anInviteWithASecretOfTheWrongSizeIsRefused() {
        Desktop desktop = new Desktop();
        Phone phone = Phone.create("Pixel", Secrets.generate(), () -> desktop.now);
        for (int size : new int[] {0, 31, 33, 65}) {
            Map<String, Object> qr = desktop.qr(2);
            qr.put("s", B64.encode(new byte[size]));
            try {
                phone.scan(qr);
                fail("a secret of " + size + " bytes must be refused");
            } catch (PhoneRejected e) {
                assertEquals("bad-message", e.code);
            }
        }
    }

    @Test
    public void anInviteWithoutAUsableSigningKeyOrExpiryIsNotANulavioCode() {
        // #769 review: a bad "d" was read only once the computer answered, and a missing "e" said "expired".
        Desktop desktop = new Desktop();
        Phone phone = Phone.create("Pixel", Secrets.generate(), () -> desktop.now);
        Object[][] cases = {{"d", null}, {"d", 7L}, {"d", "not base64!"}, {"d", B64.encode(new byte[31])},
            {"d", B64.encode(new byte[33])}, {"e", null}, {"e", "1300"}};
        for (Object[] change : cases) {
            Map<String, Object> qr = desktop.qr(2);
            if (change[1] == null) {
                qr.remove((String) change[0]);
            } else {
                qr.put((String) change[0], change[1]);
            }
            try {
                phone.scan(qr);
                fail("accepted " + change[0] + "=" + change[1]);
            } catch (PhoneRejected e) {
                assertEquals(change[0] + "=" + change[1], "bad-message", e.code);
            }
        }
    }

    @Test
    public void aSignedRequestWithoutANumericExpiryIsMalformedNotExpired() {
        byte[][] dsig = Crypto.ed25519Keypair();
        Secrets secrets = Secrets.generate();
        Map<String, Object> state = Phone.create("Pixel", secrets, () -> 0L).toState();
        Map<String, Object> paired = new TreeMap<>();
        paired.put("dsig_pk", B64.encode(dsig[1]));
        paired.put("name", "Desktop");
        Map<String, Object> desktops = new TreeMap<>();
        desktops.put("some-desktop", paired);
        state.put("desktops", desktops);
        Phone phone = Phone.fromState(state, () -> 0L);
        for (Object expiry : new Object[] {null, "300"}) {
            Map<String, Object> r = new TreeMap<>();
            r.put("desktop_id", "some-desktop");
            if (expiry != null) {
                r.put("expiry", expiry);
            }
            Map<String, Object> signed = new TreeMap<>();
            signed.put("r", r);
            signed.put("sig", B64.encode(Crypto.sign(dsig[0], Nv1.requestSigningInput(r))));
            try {
                phone.check(signed);
                fail("accepted expiry=" + expiry);
            } catch (PhoneRejected e) {
                assertEquals("expiry=" + expiry, "bad-message", e.code);
            }
        }
    }

    /** A desktop of pairing version 2, in Java, enough to answer one hello (the real one: test_companion_protocol.py). */
    private static final class Desktop {
        final long now = 1_000;
        final String invite = "invite-test";
        final byte[][] de = Crypto.x25519Keypair();
        final byte[][] dsig = Crypto.ed25519Keypair();
        final byte[] secret = Crypto.random(32);
        final byte[] nonce = Crypto.random(Nv1.NONCE_BYTES);
        final byte[] commitment = Nv1.pairingCommitment(invite, nonce);
        byte[] shared;
        byte[] t;

        Map<String, Object> qr(long version) {
            Map<String, Object> qr = new TreeMap<>();
            qr.put("v", version);
            qr.put("i", invite);
            qr.put("k", B64.encode(de[1]));
            qr.put("s", B64.encode(secret));
            qr.put("d", B64.encode(dsig[1]));
            qr.put("c", B64.encode(commitment));
            qr.put("a", "");
            qr.put("e", now + 300);
            return qr;
        }

        /** The accept, revealing {@code revealed} as the nonce. */
        Map<String, Object> accept(Map<String, Object> hello, Phone phone, byte[] psig, byte[] pkx, byte[] revealed) {
            byte[] pe = B64.decode((String) hello.get("pe"));
            shared = Crypto.x25519(de[0], pe);
            t = Nv1.pairingTranscript(invite, de[1], pe, dsig[1], psig, pkx, phone.name(), commitment);
            Map<String, Object> body = new TreeMap<>();
            body.put("dkx", B64.encode(Crypto.x25519Keypair()[1]));
            body.put("name", "Desktop");
            body.put("sig", B64.encode(Crypto.sign(dsig[0], Nv1.concat(Nv1.ascii("nv1/pair/desktop"), t))));
            body.put("n", B64.encode(revealed));
            Map<String, Object> accept = new TreeMap<>();
            accept.put("i", invite);
            accept.put("box", Nv1.sealJson(Nv1.kdf(secret, "pair/k2", shared, t), body, Nv1.ascii(invite)));
            return accept;
        }
    }

    @Test
    public void theDigitsCoverTheNonceTheQrCommittedTo() {
        Desktop desktop = new Desktop();
        Secrets secrets = Secrets.generate();
        Phone phone = Phone.create("Pixel", secrets, () -> desktop.now);
        Map<String, Object> hello = phone.scan(desktop.qr(2));
        assertEquals(2L, hello.get("v"));
        String digits = phone.onAccept(desktop.accept(hello, phone, secrets.sigPk(), secrets.kxPk(), desktop.nonce));
        assertEquals(Nv1.sasDigits(desktop.shared, desktop.t, desktop.nonce), digits);
    }

    @Test
    public void aNonceTheQrDidNotCommitToIsRefused() {
        Desktop desktop = new Desktop();
        Secrets secrets = Secrets.generate();
        Phone phone = Phone.create("Pixel", secrets, () -> desktop.now);
        for (byte[] revealed : new byte[][] {Crypto.random(Nv1.NONCE_BYTES), new byte[0]}) {
            Map<String, Object> hello = phone.scan(desktop.qr(2));
            try {
                phone.onAccept(desktop.accept(hello, phone, secrets.sigPk(), secrets.kxPk(), revealed));
                fail("the digits must not be shown");
            } catch (PhoneRejected e) {
                assertEquals("bad-commitment", e.code);
            }
            assertEquals(null, phone.pairingDesktopName());
            assertTrue(phone.desktops().isEmpty());
        }
    }

    @Test
    public void anotherPairingVersionIsRefused() {
        Desktop desktop = new Desktop();
        Phone phone = Phone.create("Pixel", Secrets.generate(), () -> desktop.now);
        for (long version : new long[] {1, 3}) {
            try {
                phone.scan(desktop.qr(version));
                fail("version " + version + " must be refused");
            } catch (PhoneRejected e) {
                assertEquals("unsupported-version", e.code);
            }
        }
        Map<String, Object> withoutCommitment = desktop.qr(2);
        withoutCommitment.remove("c");
        try {
            phone.scan(withoutCommitment);
            fail("an invite without a commitment must be refused");
        } catch (PhoneRejected e) {
            assertEquals("bad-message", e.code);
        }
    }
}
