package net.nulavio.nv1;

import java.util.Map;
import java.util.TreeMap;

/**
 * The phone's private keys: Ed25519 seed and X25519 secret key. The app keeps them encrypted under a
 * hardware key that needs the user's biometrics or device PIN for each use, and holds them in memory
 * only for one confirmation or one answer, then {@link #wipe}s them (ADR 0005, phone key storage v1).
 */
public final class Secrets {
    final byte[] sigSeed;
    final byte[] kxSk;

    Secrets(byte[] sigSeed, byte[] kxSk) {
        if (sigSeed.length != 32 || kxSk.length != 32) {
            throw new PhoneRejected("bad-key");
        }
        this.sigSeed = sigSeed;
        this.kxSk = kxSk;
    }

    public static Secrets generate() {
        return new Secrets(Crypto.ed25519Keypair()[0], Crypto.x25519Keypair()[0]);
    }

    /** From {@link #toBytes} (64 bytes), as decrypted by the app. */
    public static Secrets fromBytes(byte[] data) {
        if (data.length != 64) {
            throw new PhoneRejected("bad-key");
        }
        byte[] seed = new byte[32];
        byte[] kx = new byte[32];
        System.arraycopy(data, 0, seed, 0, 32);
        System.arraycopy(data, 32, kx, 0, 32);
        return new Secrets(seed, kx);
    }

    /** Test keys exported by the reference phone (64-byte libsodium signing key) or by {@link #toJson}. */
    public static Secrets fromJson(Map<String, Object> state) {
        byte[] sig = B64.decode(Phone.str(state, "sig_sk"));
        byte[] seed = new byte[32];
        System.arraycopy(sig, 0, seed, 0, 32);
        return new Secrets(seed, B64.decode(Phone.str(state, "kx_sk")));
    }

    public byte[] toBytes() {
        return Nv1.concat(sigSeed, kxSk);
    }

    public Map<String, Object> toJson() {
        Map<String, Object> out = new TreeMap<>();
        out.put("sig_sk", B64.encode(sigSeed));
        out.put("kx_sk", B64.encode(kxSk));
        return out;
    }

    public byte[] sigPk() {
        return Crypto.ed25519Public(sigSeed);
    }

    public byte[] kxPk() {
        return Crypto.x25519Public(kxSk);
    }

    public void wipe() {
        Crypto.wipe(sigSeed, kxSk);
    }
}
