package net.nulavio.nv1;

import com.google.crypto.tink.subtle.Ed25519Sign;
import com.google.crypto.tink.subtle.Ed25519Verify;
import com.google.crypto.tink.subtle.X25519;
import com.google.crypto.tink.subtle.XChaCha20Poly1305;
import java.security.GeneralSecurityException;
import java.security.SecureRandom;
import java.util.Arrays;
import org.bouncycastle.crypto.digests.Blake2bDigest;

/**
 * The primitives of nv1, from vetted libraries only (ADR 0005, D1): the same algorithms the desktop
 * calls in libsodium, so both sides compute the same bytes (checked by fixed vectors and by the
 * cross test against the Python desktop).
 */
public final class Crypto {
    public static final int NONCE_BYTES = 24;
    public static final int KEY_BYTES = 32;
    private static final SecureRandom RANDOM = new SecureRandom();

    private Crypto() {}

    public static byte[] random(int n) {
        byte[] out = new byte[n];
        RANDOM.nextBytes(out);
        return out;
    }

    /** {sk, pk} */
    public static byte[][] x25519Keypair() {
        byte[] sk = X25519.generatePrivateKey();
        try {
            return new byte[][] {sk, X25519.publicFromPrivate(sk)};
        } catch (java.security.InvalidKeyException e) {
            throw new IllegalStateException(e);
        }
    }

    public static byte[] x25519Public(byte[] sk) {
        try {
            return X25519.publicFromPrivate(sk);
        } catch (java.security.InvalidKeyException e) {
            throw new PhoneRejected("bad-key");
        }
    }

    /** X25519; an all-zero result (a low-order point) is refused, as libsodium's crypto_scalarmult does. */
    public static byte[] x25519(byte[] sk, byte[] pk) {
        byte[] out;
        try {
            out = X25519.computeSharedSecret(sk, pk);
        } catch (java.security.InvalidKeyException e) {
            throw new PhoneRejected("bad-key");
        }
        byte acc = 0;
        for (byte b : out) {
            acc |= b;
        }
        if (acc == 0) {
            throw new PhoneRejected("bad-key");
        }
        return out;
    }

    /** {seed (32 bytes), pk} */
    public static byte[][] ed25519Keypair() {
        try {
            Ed25519Sign.KeyPair pair = Ed25519Sign.KeyPair.newKeyPair();
            return new byte[][] {pair.getPrivateKey(), pair.getPublicKey()};
        } catch (GeneralSecurityException e) {
            throw new IllegalStateException(e);
        }
    }

    public static byte[] ed25519Public(byte[] seed) {
        try {
            return Ed25519Sign.KeyPair.newKeyPairFromSeed(seed).getPublicKey();
        } catch (GeneralSecurityException e) {
            throw new PhoneRejected("bad-key");
        }
    }

    public static byte[] sign(byte[] seed, byte[] message) {
        try {
            return new Ed25519Sign(seed).sign(message);
        } catch (GeneralSecurityException e) {
            throw new IllegalStateException(e);
        }
    }

    public static boolean verify(byte[] pk, byte[] message, byte[] signature) {
        try {
            new Ed25519Verify(pk).verify(signature, message);
            return true;
        } catch (GeneralSecurityException | IllegalArgumentException e) {
            return false;
        }
    }

    /** BLAKE2b-256, keyed when {@code key} is not null (libsodium crypto_generichash). */
    public static byte[] blake2b(byte[] key, byte[] message) {
        Blake2bDigest digest = key == null ? new Blake2bDigest(256) : new Blake2bDigest(key, 32, null, null);
        digest.update(message, 0, message.length);
        byte[] out = new byte[32];
        digest.doFinal(out, 0);
        return out;
    }

    public static byte[] hash32(byte[] message) {
        return blake2b(null, message);
    }

    /** XChaCha20-Poly1305-IETF with an explicit nonce: returns ciphertext || tag (libsodium's layout). */
    public static byte[] aeadEncrypt(byte[] key, byte[] nonce, byte[] plaintext, byte[] ad) {
        if (key.length != KEY_BYTES || nonce.length != NONCE_BYTES) {
            throw new IllegalArgumentException("bad key or nonce length");
        }
        try {
            // Tink lays out nonce || ciphertext || tag and picks the nonce itself; decrypting a message built
            // with our nonce is the same operation, so encrypt through a known-nonce wrapper below.
            return KnownNonce.encrypt(key, nonce, plaintext, ad);
        } catch (GeneralSecurityException e) {
            throw new IllegalStateException(e);
        }
    }

    public static byte[] aeadDecrypt(byte[] key, byte[] nonce, byte[] ciphertext, byte[] ad) {
        if (key.length != KEY_BYTES || nonce.length != NONCE_BYTES) {
            throw new PhoneRejected("bad-message");
        }
        byte[] framed = new byte[NONCE_BYTES + ciphertext.length];
        System.arraycopy(nonce, 0, framed, 0, NONCE_BYTES);
        System.arraycopy(ciphertext, 0, framed, NONCE_BYTES, ciphertext.length);
        try {
            return new XChaCha20Poly1305(key).decrypt(framed, ad);
        } catch (GeneralSecurityException e) {
            throw new PhoneRejected("bad-message");
        }
    }

    public static void wipe(byte[]... buffers) {
        for (byte[] b : buffers) {
            if (b != null) {
                Arrays.fill(b, (byte) 0);
            }
        }
    }

    /** Encryption with a nonce chosen by the caller, through Tink's explicit-nonce implementation. */
    private static final class KnownNonce {
        static byte[] encrypt(byte[] key, byte[] nonce, byte[] plaintext, byte[] ad) throws GeneralSecurityException {
            return new com.google.crypto.tink.aead.internal.InsecureNonceXChaCha20Poly1305(key).encrypt(nonce, plaintext, ad);
        }
    }
}
