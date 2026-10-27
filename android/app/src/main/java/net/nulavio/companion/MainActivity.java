package net.nulavio.companion;

import android.Manifest;
import android.app.Activity;
import android.app.KeyguardManager;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Typeface;
import android.hardware.biometrics.BiometricManager;
import android.hardware.biometrics.BiometricPrompt;
import android.os.Build;
import android.os.Bundle;
import android.os.CancellationSignal;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.security.keystore.KeyPermanentlyInvalidatedException;
import android.util.TypedValue;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import com.google.zxing.integration.android.IntentIntegrator;
import com.google.zxing.integration.android.IntentResult;
import java.util.Map;
import java.util.TreeMap;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.function.Consumer;
import javax.crypto.Cipher;
import net.nulavio.nv1.Json;
import net.nulavio.nv1.Link;
import net.nulavio.nv1.Phone;
import net.nulavio.nv1.PhoneRejected;
import net.nulavio.nv1.Secrets;

/**
 * The Companion's one screen: set up, scan a code from the computer, compare the 6 digits when
 * pairing, approve an unlock with biometrics or the device credential. Nothing runs in the
 * background: the phone listens on the network only while one of these steps is on screen.
 */
public final class MainActivity extends Activity {
    private static final int LOCAL_NETWORK_REQUEST = 7;
    private static final int API_37 = 37;
    private static final long SKEW_MILLIS = 120_000;

    private final ExecutorService io = Executors.newCachedThreadPool();
    private final Handler main = new Handler(Looper.getMainLooper());
    private KeyBox box;
    private Phone phone;
    private LinearLayout root;
    private Operation operation;
    private Link.Channel channel;
    private Runnable afterPermission;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        box = new KeyBox(this);
        ScrollView scroll = new ScrollView(this);
        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        int pad = dp(20);
        root.setPadding(pad, pad, pad, pad);
        scroll.addView(root);
        setContentView(scroll);
        showHome(null);
        debugCode(getIntent());
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        debugCode(intent);
    }

    /**
     * Debug builds only: a code handed over by the test driver instead of the camera (an emulator
     * cannot film the computer's screen). Release builds ignore it.
     */
    private void debugCode(Intent intent) {
        String code = intent == null ? null : intent.getStringExtra("nv1.qr");
        if (BuildConfig.DEBUG && code != null && box.ready()) {
            handleCode(code);
        }
    }

    @Override
    protected void onDestroy() {
        endOperation();
        io.shutdownNow();
        super.onDestroy();
    }

    // -- screens -------------------------------------------------------------------------

    private void showHome(String message) {
        endOperation();
        root.removeAllViews();
        title(getString(R.string.app_name));
        if (message != null) {
            text(message, 16, true);
        }
        if (!box.ready()) {
            text(getString(R.string.intro), 16, false);
            button(getString(R.string.setup_button), v -> setUp());
            return;
        }
        try {
            phone = Phone.fromState(box.loadState(), () -> System.currentTimeMillis() / 1000);
        } catch (Exception e) {
            box.reset();
            showHome(getString(R.string.error_generic, "state"));
            return;
        }
        text(getString(R.string.phone_name, phone.name()), 16, false);
        String level = box.securityLevel();
        text(getString(level.equals("STRONGBOX") ? R.string.protection_strongbox
                : level.equals("TEE") ? R.string.protection_tee : R.string.protection_software), 14, false);
        button(getString(R.string.scan_button), v -> scan());
        text(getString(R.string.computers_heading), 18, true);
        Map<String, String> computers = phone.desktops();
        if (computers.isEmpty()) {
            text(getString(R.string.no_computers), 14, false);
        }
        for (Map.Entry<String, String> computer : computers.entrySet()) {
            LinearLayout row = new LinearLayout(this);
            row.setOrientation(LinearLayout.HORIZONTAL);
            TextView name = new TextView(this);
            name.setText(computer.getValue());
            name.setTextSize(TypedValue.COMPLEX_UNIT_SP, 16);
            row.addView(name, new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1));
            Button remove = new Button(this);
            remove.setText(R.string.remove);
            remove.setOnClickListener(v -> {
                phone.forget(computer.getKey());
                save();
                showHome(getString(R.string.removed));
            });
            row.addView(remove);
            root.addView(row);
        }
    }

    private void showWorking(String message) {
        root.removeAllViews();
        title(getString(R.string.app_name));
        text(message, 16, false);
        button(getString(R.string.not_now), v -> showHome(null));
    }

    // -- set-up --------------------------------------------------------------------------

    private void setUp() {
        if (!getSystemService(KeyguardManager.class).isDeviceSecure()) {
            showHome(getString(R.string.setup_needs_lock));
            return;
        }
        Cipher cipher;
        try {
            cipher = box.newKeyEncryptCipher();
        } catch (Exception e) {
            showHome(getString(R.string.error_generic, e.getClass().getSimpleName()));
            return;
        }
        authenticate(getString(R.string.setup_prompt_title), cipher, authenticated -> {
            Secrets secrets = Secrets.generate();
            try {
                box.saveSecrets(authenticated, secrets);
                phone = Phone.create(deviceName(), secrets, () -> System.currentTimeMillis() / 1000);
                box.saveState(phone.toState());
                showHome(null);
            } catch (Exception e) {
                box.reset();
                showHome(getString(R.string.error_generic, e.getClass().getSimpleName()));
            } finally {
                secrets.wipe();
            }
        });
    }

    private String deviceName() {
        String name = Settings.Global.getString(getContentResolver(), Settings.Global.DEVICE_NAME);
        return name == null || name.isBlank() ? Build.MODEL : name;
    }

    // -- scanning --------------------------------------------------------------------------

    private void scan() {
        withLocalNetwork(() -> {
            IntentIntegrator integrator = new IntentIntegrator(this);
            integrator.setDesiredBarcodeFormats(IntentIntegrator.QR_CODE);
            integrator.setPrompt(getString(R.string.scan_prompt));
            integrator.setBeepEnabled(false);
            integrator.setOrientationLocked(false);
            integrator.initiateScan();
        });
    }

    @Override
    @SuppressWarnings("deprecation")
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        IntentResult result = IntentIntegrator.parseActivityResult(requestCode, resultCode, data);
        if (result == null) {
            super.onActivityResult(requestCode, resultCode, data);
            return;
        }
        if (result.getContents() == null) {
            showHome(null);
            return;
        }
        handleCode(result.getContents());
    }

    private void handleCode(String contents) {
        Map<String, Object> qr;
        try {
            qr = Json.parseObject(contents);
        } catch (PhoneRejected e) {
            showHome(getString(R.string.not_a_nulavio_code));
            return;
        }
        String kind = Phone.kindOf(qr);
        if ("pair".equals(kind)) {
            pair(qr);
        } else if ("unlock".equals(kind)) {
            unlock(qr);
        } else {
            showHome(getString(R.string.not_a_nulavio_code));
        }
    }

    // -- pairing ---------------------------------------------------------------------------

    private void pair(Map<String, Object> qr) {
        Map<String, Object> hello;
        try {
            hello = phone.scan(qr);
        } catch (PhoneRejected e) {
            showHome(errorText(e.code));
            return;
        }
        long deadline = ((Long) qr.get("e")) * 1000;
        showWorking(getString(R.string.waiting_for_computer));
        io.execute(() -> {
            try {
                operation = Operation.open(this, Link.instanceName("p", (String) qr.get("i")));
                channel = operation.accept(deadline);
                hello.put("t", "hello");
                channel.send(hello);
                Map<String, Object> accept = channel.recv(remaining(deadline));
                if (!"accept".equals(accept.get("t"))) {
                    throw new PhoneRejected(String.valueOf(accept.getOrDefault("code", "bad-message")));
                }
                String digits = phone.onAccept(accept);
                String computer = phone.pairingDesktopName();
                main.post(() -> showDigits(digits, computer, deadline));
            } catch (Exception e) {
                phone.cancelPairing();
                fail(e);
            }
        });
    }

    private void showDigits(String digits, String computer, long deadline) {
        root.removeAllViews();
        title(getString(R.string.compare_title, computer));
        TextView big = text(digits.substring(0, 3) + " " + digits.substring(3), 40, true);
        big.setTypeface(Typeface.MONOSPACE, Typeface.BOLD);
        big.setContentDescription(digits.replace("", " ").trim());
        button(getString(R.string.digits_match), v -> {
            Cipher cipher = openCipher();
            if (cipher == null) {
                return;
            }
            authenticate(getString(R.string.confirm_prompt_title, computer), cipher, authenticated -> {
                showWorking(getString(R.string.working));
                io.execute(() -> {
                    try {
                        Secrets secrets = box.openSecrets(authenticated);
                        Map<String, Object> confirm;
                        try {
                            confirm = phone.confirm(secrets);
                        } finally {
                            secrets.wipe();
                        }
                        confirm.put("t", "confirm");
                        channel.send(confirm);
                        Map<String, Object> end = channel.recv(remaining(deadline));
                        if (!"paired".equals(end.get("t"))) {
                            throw new PhoneRejected(String.valueOf(end.getOrDefault("code", "bad-message")));
                        }
                        box.saveState(phone.toState());
                        main.post(() -> showHome(getString(R.string.paired, computer)));
                    } catch (Exception e) {
                        reloadPhone();
                        fail(e);
                    }
                });
            });
        });
        button(getString(R.string.digits_differ), v -> io.execute(() -> {
            try {
                Map<String, Object> cancel = new TreeMap<>();
                cancel.put("t", "cancel");
                channel.send(cancel);
            } catch (Exception ignored) {
                // the computer stops the pairing either way
            }
            phone.cancelPairing();
            main.post(() -> showHome(getString(R.string.pairing_cancelled)));
        }));
    }

    // -- unlock ----------------------------------------------------------------------------

    @SuppressWarnings("unchecked")
    private void unlock(Map<String, Object> signed) {
        Map<String, Object> request;
        try {
            request = phone.check(signed);
        } catch (PhoneRejected e) {
            showHome(errorText(e.code));
            return;
        }
        String profile = String.valueOf(request.get("profile_name"));
        String computer = String.valueOf(request.get("desktop_name"));
        long deadline = ((Long) request.get("expiry")) * 1000 + SKEW_MILLIS;
        // Listen now, so the computer can show that the phone has the request while the user decides.
        CompletableFuture<Link.Channel> connected = CompletableFuture.supplyAsync(() -> {
            try {
                operation = Operation.open(this, Link.instanceName("u", (String) request.get("req_id")));
                return operation.accept(deadline);
            } catch (Exception e) {
                throw new java.util.concurrent.CompletionException(e);
            }
        }, io);
        root.removeAllViews();
        title(getString(R.string.unlock_title, profile, computer));
        text(getString(R.string.unlock_hint), 14, false);
        button(getString(R.string.unlock_button), v -> {
            Cipher cipher = openCipher();
            if (cipher == null) {
                return;
            }
            authenticate(getString(R.string.unlock_prompt_title, profile), cipher, authenticated -> {
                showWorking(getString(R.string.working));
                io.execute(() -> {
                    try {
                        Map<String, Object> response;
                        Secrets secrets = box.openSecrets(authenticated);
                        try {
                            response = phone.answer(signed, Phone.Answer.APPROVE, secrets);
                        } finally {
                            secrets.wipe();
                        }
                        box.saveState(phone.toState()); // remember the answered request at once (replay)
                        channel = connected.get(remaining(deadline), TimeUnit.MILLISECONDS);
                        Map<String, Object> message = new TreeMap<>(response);
                        message.put("t", "response");
                        channel.send(message);
                        Map<String, Object> end = channel.recv(remaining(deadline));
                        if (!"ok".equals(end.get("t"))) {
                            throw new PhoneRejected(String.valueOf(end.getOrDefault("code", "bad-message")));
                        }
                        main.post(() -> showHome(getString(R.string.unlocked, profile, computer)));
                    } catch (java.util.concurrent.TimeoutException e) {
                        fail(new PhoneRejected("unreachable"));
                    } catch (Exception e) {
                        fail(e);
                    }
                });
            });
        });
        // Not now: nothing is sent; the computer offers its other methods.
        button(getString(R.string.not_now), v -> showHome(null));
    }

    // -- helpers ---------------------------------------------------------------------------

    private Cipher openCipher() {
        try {
            return box.decryptCipher();
        } catch (KeyPermanentlyInvalidatedException e) {
            box.reset();
            showHome(getString(R.string.error_keys_invalidated));
        } catch (Exception e) {
            showHome(getString(R.string.error_generic, e.getClass().getSimpleName()));
        }
        return null;
    }

    private void authenticate(String title, Cipher cipher, Consumer<Cipher> then) {
        BiometricPrompt prompt = new BiometricPrompt.Builder(this)
                .setTitle(title)
                .setAllowedAuthenticators(BiometricManager.Authenticators.BIOMETRIC_STRONG
                        | BiometricManager.Authenticators.DEVICE_CREDENTIAL)
                .build();
        prompt.authenticate(new BiometricPrompt.CryptoObject(cipher), new CancellationSignal(), getMainExecutor(),
                new BiometricPrompt.AuthenticationCallback() {
                    @Override
                    public void onAuthenticationSucceeded(BiometricPrompt.AuthenticationResult result) {
                        then.accept(result.getCryptoObject().getCipher());
                    }

                    @Override
                    public void onAuthenticationError(int code, CharSequence message) {
                        // Cancelled or locked out: nothing is sent, nothing unlocks.
                        showHome(String.valueOf(message));
                    }
                });
    }

    private void withLocalNetwork(Runnable action) {
        if (Build.VERSION.SDK_INT >= API_37
                && checkSelfPermission(Manifest.permission.ACCESS_LOCAL_NETWORK) != PackageManager.PERMISSION_GRANTED) {
            afterPermission = action;
            requestPermissions(new String[] {Manifest.permission.ACCESS_LOCAL_NETWORK}, LOCAL_NETWORK_REQUEST);
            return;
        }
        action.run();
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(code, permissions, results);
        if (code != LOCAL_NETWORK_REQUEST) {
            return;
        }
        Runnable action = afterPermission;
        afterPermission = null;
        if (results.length > 0 && results[0] == PackageManager.PERMISSION_GRANTED && action != null) {
            action.run();
        } else {
            showHome(getString(R.string.local_network_needed));
        }
    }

    private void fail(Exception e) {
        String code = e instanceof PhoneRejected ? ((PhoneRejected) e).code
                : e.getCause() instanceof PhoneRejected ? ((PhoneRejected) e.getCause()).code : e.getClass().getSimpleName();
        main.post(() -> showHome(errorText(code)));
    }

    private String errorText(String code) {
        switch (code) {
            case "expired": return getString(R.string.error_expired);
            case "replay": return getString(R.string.error_replay);
            case "unpaired-desktop": return getString(R.string.error_unpaired);
            case "bad-signature": return getString(R.string.error_bad_signature);
            case "not-for-this-phone": return getString(R.string.error_not_for_this_phone);
            case "unreachable": case "timeout": case "closed": return getString(R.string.error_unreachable);
            case "sas-mismatch": return getString(R.string.pairing_cancelled);
            default: return getString(R.string.error_generic, code);
        }
    }

    private void save() {
        try {
            box.saveState(phone.toState());
        } catch (Exception e) {
            showHome(getString(R.string.error_generic, "save"));
        }
    }

    private void reloadPhone() {
        try {
            phone = Phone.fromState(box.loadState(), () -> System.currentTimeMillis() / 1000);
        } catch (Exception ignored) {
            // showHome reloads it
        }
    }

    private void endOperation() {
        if (channel != null) {
            channel.close();
            channel = null;
        }
        if (operation != null) {
            operation.close();
            operation = null;
        }
    }

    private static int remaining(long deadlineMillis) {
        return (int) Math.max(1, deadlineMillis - System.currentTimeMillis());
    }

    private int dp(int value) {
        return (int) (value * getResources().getDisplayMetrics().density);
    }

    private void title(String value) {
        TextView view = text(value, 22, true);
        view.setAccessibilityHeading(true);
    }

    private TextView text(String value, int sp, boolean bold) {
        TextView view = new TextView(this);
        view.setText(value);
        view.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp);
        if (bold) {
            view.setTypeface(view.getTypeface(), Typeface.BOLD);
        }
        view.setPadding(0, dp(8), 0, dp(8));
        root.addView(view);
        return view;
    }

    private void button(String label, View.OnClickListener listener) {
        Button button = new Button(this);
        button.setText(label);
        button.setOnClickListener(listener);
        root.addView(button);
    }
}
