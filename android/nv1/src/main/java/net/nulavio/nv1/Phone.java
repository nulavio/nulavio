package net.nulavio.nv1;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.function.LongSupplier;

/**
 * The Companion's side of nv1 (docs/architecture/vault-and-unlock.md), message for message as
 * tests/lib/phone_reference.py. This object holds only public state (its public keys, paired
 * desktops, answered request ids); the private keys come in as {@link Secrets} for the two steps
 * that need them, {@link #confirm} and {@link #answer}, after the user authenticated on the phone.
 */
public final class Phone {
    public static final int MAX_NAME = 64;
    private static final int SEEN_LIMIT = 4096;

    private final byte[] sigPk;
    private final byte[] kxPk;
    private final String name;
    private final String phoneId;
    /** desktop id -> {dsig_pk (base64), name} */
    private final Map<String, Map<String, Object>> desktops = new TreeMap<>();
    private final Set<String> seen = new LinkedHashSet<>();
    private final LongSupplier clock;
    private Pairing pairing;

    /** The decision the user makes on the phone for an unlock request. */
    public enum Answer { APPROVE, DECLINE, BIOMETRIC_UNAVAILABLE, DEVICE_LOCKED }

    private static final class Pairing {
        Map<String, Object> qr;
        byte[] pePk;
        byte[] shared;
        byte[] secret;
        byte[] t;
        byte[] dsigPk;
        String desktopName;
    }

    private Phone(byte[] sigPk, byte[] kxPk, String name, LongSupplier clock) {
        this.sigPk = sigPk;
        this.kxPk = kxPk;
        this.name = limitName(name);
        this.phoneId = Nv1.idFor(sigPk);
        this.clock = clock;
    }

    static String limitName(String name) {
        int[] cps = name.codePoints().limit(MAX_NAME).toArray();
        return new String(cps, 0, cps.length); // the desktop keeps at most 64 characters, so sign the same
    }

    /** A new phone identity for these secrets (generated once, when the app is set up). */
    public static Phone create(String name, Secrets secrets, LongSupplier clock) {
        return new Phone(secrets.sigPk(), secrets.kxPk(), name, clock);
    }

    /** Restore from {@link #toState} (public keys, desktops, answered ids). */
    public static Phone fromState(Map<String, Object> state, LongSupplier clock) {
        Phone phone = new Phone(B64.decode(str(state, "sig_pk")), B64.decode(str(state, "kx_pk")), str(state, "name"), clock);
        Object known = state.get("desktops");
        if (known instanceof Map) {
            for (Map.Entry<?, ?> e : ((Map<?, ?>) known).entrySet()) {
                Map<?, ?> d = (Map<?, ?>) e.getValue();
                Map<String, Object> entry = new TreeMap<>();
                entry.put("dsig_pk", d.get("dsig_pk"));
                entry.put("name", d.get("name"));
                phone.desktops.put((String) e.getKey(), entry);
            }
        }
        Object answered = state.get("seen");
        if (answered instanceof List) {
            for (Object id : (List<?>) answered) {
                phone.seen.add((String) id);
            }
        }
        return phone;
    }

    public Map<String, Object> toState() {
        Map<String, Object> out = new TreeMap<>();
        out.put("name", name);
        out.put("sig_pk", B64.encode(sigPk));
        out.put("kx_pk", B64.encode(kxPk));
        out.put("desktops", new TreeMap<>(desktops));
        out.put("seen", new ArrayList<>(seen));
        return out;
    }

    public String phoneId() {
        return phoneId;
    }

    public String name() {
        return name;
    }

    /** Paired desktops: id -> name. */
    public Map<String, String> desktops() {
        Map<String, String> out = new TreeMap<>();
        desktops.forEach((id, d) -> out.put(id, (String) d.get("name")));
        return out;
    }

    public boolean forget(String desktopId) {
        return desktops.remove(desktopId) != null;
    }

    /** The secrets belong to this phone (the app checks after decrypting them). */
    public boolean owns(Secrets secrets) {
        return java.util.Arrays.equals(secrets.sigPk(), sigPk) && java.util.Arrays.equals(secrets.kxPk(), kxPk);
    }

    // -- pairing ---------------------------------------------------------------------------

    /** Kind of QR: "pair" (an invite), "unlock" (a signed request) or null. */
    public static String kindOf(Map<String, Object> qr) {
        if (qr.containsKey("r") && qr.containsKey("sig")) {
            return "unlock";
        }
        if (Long.valueOf(1).equals(qr.get("v")) && qr.containsKey("s") && qr.containsKey("i")) {
            return "pair";
        }
        return null;
    }

    public Map<String, Object> scan(Map<String, Object> qr) {
        if (!Long.valueOf(1).equals(qr.get("v")) || !(qr.get("e") instanceof Long) || now() > (Long) qr.get("e")) {
            throw new PhoneRejected("expired");
        }
        String invite = str(qr, "i");
        byte[] dePk = B64.decode(str(qr, "k"));
        byte[] secret = B64.decode(str(qr, "s"));
        byte[][] pe = Crypto.x25519Keypair();
        byte[] shared = Crypto.x25519(pe[0], dePk);
        Crypto.wipe(pe[0]);
        byte[] k1 = Nv1.kdf(secret, "pair/k1", shared, invite, dePk, pe[1]);
        Map<String, Object> body = new TreeMap<>();
        body.put("psig", B64.encode(sigPk));
        body.put("pkx", B64.encode(kxPk));
        body.put("name", name);
        Map<String, Object> box = Nv1.sealJson(k1, body, Nv1.ascii(invite));
        Crypto.wipe(k1);
        pairing = new Pairing();
        pairing.qr = qr;
        pairing.pePk = pe[1];
        pairing.shared = shared;
        pairing.secret = secret;
        Map<String, Object> hello = new TreeMap<>();
        hello.put("i", invite);
        hello.put("pe", B64.encode(pe[1]));
        hello.put("box", box);
        return hello;
    }

    /** Check the desktop's signature against the key in the QR; returns the 6 digits to show. */
    public String onAccept(Map<String, Object> msg) {
        Pairing p = requirePairing();
        String invite = str(p.qr, "i");
        byte[] dsigPk = B64.decode(str(p.qr, "d"));
        byte[] t = Nv1.transcript(invite, B64.decode(str(p.qr, "k")), p.pePk, dsigPk, sigPk, kxPk, name);
        Map<String, Object> body;
        byte[] k2 = Nv1.kdf(p.secret, "pair/k2", p.shared, t);
        try {
            body = Nv1.unsealJson(k2, msg.get("box"), Nv1.ascii(invite));
        } catch (PhoneRejected e) {
            cancelPairing();
            throw new PhoneRejected("bad-message"); // the transcript differs: keys were swapped
        } finally {
            Crypto.wipe(k2);
        }
        if (!Crypto.verify(dsigPk, Nv1.concat(Nv1.ascii("nv1/pair/desktop"), t), B64.decode(str(body, "sig")))) {
            cancelPairing();
            throw new PhoneRejected("bad-signature");
        }
        p.t = t;
        p.dsigPk = dsigPk;
        p.desktopName = str(body, "name");
        return Nv1.sasDigits(p.shared, t);
    }

    public String pairingDesktopName() {
        return pairing == null ? null : pairing.desktopName;
    }

    /** The user said the digits match (and authenticated): remember the desktop and return the confirmation. */
    public Map<String, Object> confirm(Secrets secrets) {
        Pairing p = requirePairing();
        if (p.t == null || !owns(secrets)) {
            throw new PhoneRejected("bad-state");
        }
        pairing = null;
        byte[] sig = Crypto.sign(secrets.sigSeed, Nv1.concat(Nv1.ascii("nv1/pair/phone"), p.t));
        Map<String, Object> desktop = new TreeMap<>();
        desktop.put("dsig_pk", B64.encode(p.dsigPk));
        desktop.put("name", p.desktopName);
        desktops.put(Nv1.idFor(p.dsigPk), desktop);
        String invite = str(p.qr, "i");
        byte[] k3 = Nv1.kdf(p.secret, "pair/k3", p.shared, p.t);
        Map<String, Object> body = new TreeMap<>();
        body.put("sig", B64.encode(sig));
        Map<String, Object> out = new TreeMap<>();
        out.put("i", invite);
        out.put("box", Nv1.sealJson(k3, body, Nv1.ascii(invite)));
        Crypto.wipe(k3, p.shared, p.secret);
        return out;
    }

    public void cancelPairing() {
        if (pairing != null) {
            Crypto.wipe(pairing.shared, pairing.secret);
            pairing = null;
        }
    }

    private Pairing requirePairing() {
        if (pairing == null) {
            throw new PhoneRejected("bad-state");
        }
        return pairing;
    }

    // -- unlock ------------------------------------------------------------------------------

    /**
     * Check a signed unlock request before asking the user. Returns what to show: the request with the
     * desktop's name from this phone's own pairing record, never the name the request carries (audit V3).
     * Throws: unpaired-desktop, bad-signature, expired, bad-expiry, replay, not-for-this-phone.
     */
    public Map<String, Object> check(Map<String, Object> signed) {
        Map<String, Object> r = verify(signed);
        Map<String, Object> shown = new TreeMap<>(r);
        shown.put("desktop_name", desktops.get(r.get("desktop_id")).get("name"));
        return shown;
    }

    /** The signed request itself, checked; the answer is computed over exactly these bytes. */
    @SuppressWarnings("unchecked")
    private Map<String, Object> verify(Map<String, Object> signed) {
        if (!(signed.get("r") instanceof Map)) {
            throw new PhoneRejected("bad-message");
        }
        Map<String, Object> r = (Map<String, Object>) signed.get("r");
        Map<String, Object> desktop = desktops.get(r.get("desktop_id"));
        if (desktop == null) {
            throw new PhoneRejected("unpaired-desktop");
        }
        byte[] dsigPk = B64.decode((String) desktop.get("dsig_pk"));
        if (!Crypto.verify(dsigPk, Nv1.requestSigningInput(r), B64.decode(str(signed, "sig")))) {
            throw new PhoneRejected("bad-signature");
        }
        if (!(r.get("expiry") instanceof Long) || now() > (Long) r.get("expiry") + Nv1.CLOCK_SKEW) {
            throw new PhoneRejected("expired");
        }
        if ((Long) r.get("expiry") > now() + Nv1.MAX_REQUEST_AHEAD) {
            throw new PhoneRejected("bad-expiry"); // made to stay valid longer than one request may
        }
        if (seen.contains(str(r, "req_id"))) {
            throw new PhoneRejected("replay");
        }
        if (!phoneId.equals(r.get("phone_id")) || !"unlock-profile".equals(r.get("op"))) {
            throw new PhoneRejected("not-for-this-phone");
        }
        return r;
    }

    /** The answer to a request the user decided on (after authenticating): the response to send, signed either way. */
    public Map<String, Object> answer(Map<String, Object> signed, Answer answer, Secrets secrets) {
        if (!owns(secrets)) {
            throw new PhoneRejected("bad-state");
        }
        Map<String, Object> r = verify(signed);
        String reqId = str(r, "req_id");
        seen.add(reqId);
        while (seen.size() > SEEN_LIMIT) {
            seen.remove(seen.iterator().next());
        }
        byte[] requestHash = Crypto.hash32(Json.canonical(r));
        if (answer != Answer.APPROVE) {
            String code = answer == Answer.DECLINE ? "declined"
                    : answer == Answer.BIOMETRIC_UNAVAILABLE ? "biometric-unavailable" : "device-locked";
            Map<String, Object> error = new TreeMap<>();
            error.put("error", code);
            return signedResponse(reqId, requestHash, error, true, secrets);
        }
        byte[] ephPk = B64.decode(str(r, "eph_pk"));
        byte[] z = Crypto.x25519(secrets.kxSk, ephPk);
        byte[] dsigPk = B64.decode((String) desktops.get(r.get("desktop_id")).get("dsig_pk"));
        byte[] kek = Nv1.phoneKek(z, str(r, "profile_id"), str(r, "envelope_id"), phoneId, ephPk, dsigPk);
        byte[] shared = Crypto.x25519(secrets.kxSk, B64.decode(str(r, "s_pk")));
        byte[] rk = Nv1.responseKey(shared, requestHash);
        Map<String, Object> box = Nv1.seal(rk, kek, Nv1.ascii(reqId));
        Crypto.wipe(z, kek, shared, rk);
        return signedResponse(reqId, requestHash, box, false, secrets);
    }

    private Map<String, Object> signedResponse(String reqId, byte[] requestHash, Map<String, Object> payload, boolean error,
                                               Secrets secrets) {
        byte[] sig = Crypto.sign(secrets.sigSeed, Nv1.responseSigningInput(requestHash, payload));
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("req_id", reqId);
        out.put("phone_id", phoneId);
        out.put("sig", B64.encode(sig));
        if (error) {
            out.put("error", payload.get("error"));
        } else {
            out.put("box", payload);
        }
        return out;
    }

    private long now() {
        return clock.getAsLong();
    }

    static String str(Map<String, Object> m, String key) {
        Object v = m.get(key);
        if (!(v instanceof String)) {
            throw new PhoneRejected("bad-message");
        }
        return (String) v;
    }

    static byte[] utf8(String s) {
        return s.getBytes(StandardCharsets.UTF_8);
    }
}
