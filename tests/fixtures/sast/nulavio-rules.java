// Test cases for ci/sast/nulavio-rules.yml (Java rules); never compiled.
// A line annotated "ruleid" must match the rule named, a line annotated "ok" must not.
//   scripts/security/scan.sh opengrep-rules

class NulavioRulesCases {
    void weakCrypto() throws Exception {
        // ruleid: nulavio-java-weak-crypto
        Cipher a = Cipher.getInstance("AES");
        // ruleid: nulavio-java-weak-crypto
        Cipher b = Cipher.getInstance("AES/ECB/PKCS5Padding");
        // ruleid: nulavio-java-weak-crypto
        Cipher c = Cipher.getInstance("DESede/CBC/PKCS5Padding");
        // ruleid: nulavio-java-weak-crypto
        MessageDigest d = MessageDigest.getInstance("SHA-1");
        // ruleid: nulavio-java-weak-crypto
        MessageDigest e = MessageDigest.getInstance("MD5");
        // ruleid: nulavio-java-weak-crypto
        Random f = new Random();
        // ruleid: nulavio-java-weak-crypto
        SecureRandom g = SecureRandom.getInstance("SHA1PRNG");
        // ok: nulavio-java-weak-crypto
        Cipher h = Cipher.getInstance("AES/GCM/NoPadding");
        // ok: nulavio-java-weak-crypto
        MessageDigest i = MessageDigest.getInstance("SHA-256");
        // ok: nulavio-java-weak-crypto
        SecureRandom j = new SecureRandom();
    }

    void tls(HttpsURLConnection connection) {
        // ruleid: nulavio-java-tls-verification-off
        connection.setHostnameVerifier(verifier);
        // ruleid: nulavio-java-tls-verification-off
        HttpsURLConnection.setDefaultSSLSocketFactory(factory);
        // ok: nulavio-java-tls-verification-off
        connection.setConnectTimeout(5000);
    }
}

class TrustEverything implements X509TrustManager {
    // ruleid: nulavio-java-tls-verification-off
    public void checkServerTrusted(X509Certificate[] chain, String authType) {}

    // ruleid: nulavio-java-tls-verification-off
    public X509Certificate[] getAcceptedIssuers() { return null; }
}

class AnyHost implements HostnameVerifier {
    // ruleid: nulavio-java-tls-verification-off
    public boolean verify(String hostname, SSLSession session) { return true; }
}

class Storage {
    void save(Context context) throws Exception {
        // ruleid: nulavio-android-unsafe-storage-or-manifest
        context.openFileOutput("keys", Context.MODE_WORLD_READABLE);
        // ok: nulavio-android-unsafe-storage-or-manifest
        context.openFileOutput("keys", Context.MODE_PRIVATE);
    }
}
