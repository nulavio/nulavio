package net.nulavio.companion;

import android.content.Context;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyInfo;
import android.security.keystore.KeyProperties;
import android.security.keystore.StrongBoxUnavailableException;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.GeneralSecurityException;
import java.security.KeyStore;
import java.util.Arrays;
import java.util.Map;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.SecretKeyFactory;
import javax.crypto.spec.GCMParameterSpec;
import net.nulavio.nv1.Json;
import net.nulavio.nv1.Secrets;

/**
 * Where the Companion keeps its keys (ADR 0005, phone key storage v1).
 *
 * <p>The phone's nv1 private keys are encrypted with an AES-256-GCM key that lives in the Android
 * Keystore (StrongBox when the phone has it), cannot be exported, and needs the user's biometrics or
 * device credential for every single use (timeout 0, used through a BiometricPrompt CryptoObject).
 * The public state (public keys, paired computers, answered request ids) is a plain file in the
 * app's private storage: it holds nothing that unlocks a profile.
 */
final class KeyBox {
    private static final String ALIAS = "nv1-secrets";
    private static final String STORE = "AndroidKeyStore";
    private static final int IV_BYTES = 12;

    private final File secretsFile;
    private final File stateFile;

    KeyBox(Context context) {
        secretsFile = new File(context.getFilesDir(), "secrets.bin");
        stateFile = new File(context.getFilesDir(), "phone.json");
    }

    boolean ready() {
        return secretsFile.isFile() && stateFile.isFile() && key() != null;
    }

    private static SecretKey key() {
        try {
            KeyStore store = KeyStore.getInstance(STORE);
            store.load(null);
            return (SecretKey) store.getKey(ALIAS, null);
        } catch (GeneralSecurityException | IOException e) {
            return null;
        }
    }

    private static void createKey(boolean strongBox) throws GeneralSecurityException {
        KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, STORE);
        generator.init(new KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .setUserAuthenticationRequired(true)
                .setUserAuthenticationParameters(0,
                        KeyProperties.AUTH_BIOMETRIC_STRONG | KeyProperties.AUTH_DEVICE_CREDENTIAL)
                .setInvalidatedByBiometricEnrollment(true)
                .setUnlockedDeviceRequired(true)
                .setIsStrongBoxBacked(strongBox)
                .build());
        generator.generateKey();
    }

    /** A new key (StrongBox if the phone has it) and a cipher to encrypt the new secrets once the user authenticates. */
    Cipher newKeyEncryptCipher() throws GeneralSecurityException, IOException {
        reset();
        try {
            createKey(true);
        } catch (StrongBoxUnavailableException e) {
            createKey(false);
        }
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, key());
        return cipher;
    }

    /** A cipher for opening the secrets; usable only after the user authenticates (BiometricPrompt). */
    Cipher decryptCipher() throws GeneralSecurityException, IOException {
        byte[] data = Files.readAllBytes(secretsFile.toPath());
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128, Arrays.copyOf(data, IV_BYTES)));
        return cipher;
    }

    void saveSecrets(Cipher authenticated, Secrets secrets) throws GeneralSecurityException, IOException {
        byte[] plain = secrets.toBytes();
        try {
            byte[] sealed = authenticated.doFinal(plain);
            byte[] iv = authenticated.getIV();
            byte[] out = new byte[iv.length + sealed.length];
            System.arraycopy(iv, 0, out, 0, iv.length);
            System.arraycopy(sealed, 0, out, iv.length, sealed.length);
            write(secretsFile, out);
        } finally {
            Arrays.fill(plain, (byte) 0);
        }
    }

    Secrets openSecrets(Cipher authenticated) throws GeneralSecurityException, IOException {
        byte[] data = Files.readAllBytes(secretsFile.toPath());
        byte[] plain = authenticated.doFinal(data, IV_BYTES, data.length - IV_BYTES);
        try {
            return Secrets.fromBytes(plain);
        } finally {
            Arrays.fill(plain, (byte) 0);
        }
    }

    Map<String, Object> loadState() throws IOException {
        return Json.parseObject(Files.readAllBytes(stateFile.toPath()));
    }

    void saveState(Map<String, Object> state) throws IOException {
        write(stateFile, Json.canonical(state));
    }

    /** STRONGBOX, TEE or SOFTWARE, as the Keystore reports it for the key in use. */
    String securityLevel() {
        try {
            SecretKey k = key();
            KeyInfo info = (KeyInfo) SecretKeyFactory.getInstance(k.getAlgorithm(), STORE).getKeySpec(k, KeyInfo.class);
            if (android.os.Build.VERSION.SDK_INT < android.os.Build.VERSION_CODES.S) {
                return legacyLevel(info); // Android 11: no StrongBox distinction in KeyInfo
            }
            int level = info.getSecurityLevel();
            if (level == KeyProperties.SECURITY_LEVEL_STRONGBOX) {
                return "STRONGBOX";
            }
            if (level == KeyProperties.SECURITY_LEVEL_TRUSTED_ENVIRONMENT) {
                return "TEE";
            }
            return "SOFTWARE";
        } catch (GeneralSecurityException | RuntimeException e) {
            return "SOFTWARE";
        }
    }

    @SuppressWarnings("deprecation")
    private static String legacyLevel(KeyInfo info) {
        return info.isInsideSecureHardware() ? "TEE" : "SOFTWARE";
    }

    /** Forget this phone's identity: the key and both files. Paired computers must remove it too. */
    void reset() {
        try {
            KeyStore store = KeyStore.getInstance(STORE);
            store.load(null);
            store.deleteEntry(ALIAS);
        } catch (GeneralSecurityException | IOException ignored) {
            // nothing to delete
        }
        secretsFile.delete();
        stateFile.delete();
    }

    private static void write(File target, byte[] data) throws IOException {
        File tmp = new File(target.getParentFile(), target.getName() + ".tmp");
        try (FileOutputStream out = new FileOutputStream(tmp)) {
            out.write(data);
            out.getFD().sync();
        }
        if (!tmp.renameTo(target)) {
            throw new IOException("could not save " + target.getName());
        }
    }

    static String utf8(byte[] data) {
        return new String(data, StandardCharsets.UTF_8);
    }
}
