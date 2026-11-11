package net.nulavio.companion;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.app.KeyguardManager;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.res.ColorStateList;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.RippleDrawable;
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
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.TextView;
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
    private static final int SCAN_REQUEST = 9;
    private static final int API_37 = 37;
    private static final long SKEW_MILLIS = 120_000;

    private final ExecutorService io = Executors.newCachedThreadPool();
    private final Handler main = new Handler(Looper.getMainLooper());
    private KeyBox box;
    private Phone phone;
    private LinearLayout root;
    private Operation operation;
    private Link.Channel channel;
    /** An unlock request's connection, accepted while the user decides; closed by "Not now". */
    private volatile CompletableFuture<Link.Channel> pending;
    private Runnable afterPermission;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        box = new KeyBox(this);
        ScrollView scroll = new ScrollView(this);
        Insets.pad(scroll);
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
        showHome(message, false);
    }

    /** The home screen, with an optional notice on top: a problem (nothing happened) or news. */
    private void showHome(String message, boolean problem) {
        endOperation();
        root.removeAllViews();
        title(getString(R.string.app_name));
        if (message != null) {
            notice(message, problem);
        }
        if (!box.ready()) {
            text(getString(R.string.intro), 16, false);
            primaryButton(getString(R.string.setup_button), v -> setUp());
            footer();
            return;
        }
        try {
            phone = Phone.fromState(box.loadState(), () -> System.currentTimeMillis() / 1000);
        } catch (Exception e) {
            box.reset();
            showProblem(getString(R.string.error_generic, "state"));
            return;
        }
        text(getString(R.string.phone_name, phone.name()), 16, false);
        String level = box.securityLevel();
        text(getString(level.equals("STRONGBOX") ? R.string.protection_strongbox
                : level.equals("TEE") ? R.string.protection_tee : R.string.protection_software), 14, false);
        primaryButton(getString(R.string.scan_button), v -> scan());
        heading(getString(R.string.computers_heading));
        Map<String, String> computers = phone.desktops();
        if (computers.isEmpty()) {
            text(getString(R.string.no_computers), 14, false);
        }
        for (Map.Entry<String, String> computer : computers.entrySet()) {
            LinearLayout row = new LinearLayout(this);
            row.setOrientation(LinearLayout.HORIZONTAL);
            row.setGravity(Gravity.CENTER_VERTICAL);
            row.setPadding(dp(16), dp(8), dp(8), dp(8));
            row.setBackground(rounded(color(R.color.surface), color(R.color.border), dp(12)));
            TextView name = new TextView(this);
            name.setText(computer.getValue());
            name.setTextColor(color(R.color.text_primary));
            name.setTextSize(TypedValue.COMPLEX_UNIT_SP, 16);
            row.addView(name, new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1));
            Button remove = styled(new Button(this), false);
            remove.setText(R.string.remove);
            remove.setTextColor(color(R.color.critical_text));
            remove.setOnClickListener(v -> confirmRemove(computer.getKey(), computer.getValue()));
            row.addView(remove, new LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, dp(44)));
            root.addView(row, spaced(dp(8)));
        }
        footer();
    }

    private void confirmRemove(String id, String name) {
        new AlertDialog.Builder(this)
                .setTitle(getString(R.string.remove_title, name))
                .setMessage(getString(R.string.remove_body, name))
                .setNegativeButton(R.string.cancel, null)
                .setPositiveButton(R.string.remove, (dialog, which) -> {
                    phone.forget(id);
                    save();
                    showHome(getString(R.string.removed));
                })
                .show();
    }

    private void showProblem(String message) {
        showHome(message, true);
    }

    private void showWorking(String message) {
        root.removeAllViews();
        title(getString(R.string.app_name));
        ProgressBar spinner = new ProgressBar(this);
        spinner.setIndeterminateTintList(ColorStateList.valueOf(color(R.color.accent)));
        root.addView(spinner, spaced(dp(16)));
        TextView status = text(message, 16, false);
        status.setGravity(Gravity.CENTER_HORIZONTAL);
        secondaryButton(getString(R.string.not_now), v -> showHome(null));
    }

    // -- set-up --------------------------------------------------------------------------

    private void setUp() {
        if (!getSystemService(KeyguardManager.class).isDeviceSecure()) {
            showProblem(getString(R.string.setup_needs_lock));
            return;
        }
        Cipher cipher;
        try {
            cipher = box.newKeyEncryptCipher();
        } catch (Exception e) {
            showProblem(getString(R.string.error_generic, e.getClass().getSimpleName()));
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
                showProblem(getString(R.string.error_generic, e.getClass().getSimpleName()));
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
        withLocalNetwork(() -> startActivityForResult(new Intent(this, ScanActivity.class), SCAN_REQUEST));
    }

    @Override
    @SuppressWarnings("deprecation")
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        if (requestCode != SCAN_REQUEST) {
            super.onActivityResult(requestCode, resultCode, data);
            return;
        }
        String code = data == null ? null : data.getStringExtra(ScanActivity.EXTRA_CODE);
        if (resultCode == RESULT_OK && code != null) {
            handleCode(code);
        } else if (data != null && data.getBooleanExtra(ScanActivity.EXTRA_CAMERA_DENIED, false)) {
            showProblem(getString(R.string.camera_needed));
        } else {
            showHome(null);
        }
    }

    private void handleCode(String contents) {
        Map<String, Object> qr;
        try {
            qr = Json.parseObject(contents);
        } catch (PhoneRejected e) {
            showProblem(getString(R.string.not_a_nulavio_code));
            return;
        }
        String kind = Phone.kindOf(qr);
        if ("pair".equals(kind)) {
            pair(qr);
        } else if ("unlock".equals(kind)) {
            unlock(qr);
        } else {
            showProblem(getString(R.string.not_a_nulavio_code));
        }
    }

    // -- pairing ---------------------------------------------------------------------------

    private void pair(Map<String, Object> qr) {
        Map<String, Object> hello;
        try {
            hello = phone.scan(qr);
        } catch (PhoneRejected e) {
            showProblem(errorText(e.code));
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
        TextView big = text(digits.substring(0, 3) + " " + digits.substring(3), 44, true);
        big.setTypeface(Typeface.MONOSPACE, Typeface.BOLD);
        big.setTextColor(color(R.color.text_primary));
        big.setGravity(Gravity.CENTER);
        big.setPadding(0, dp(20), 0, dp(20));
        big.setBackground(rounded(color(R.color.surface), color(R.color.border), dp(16)));
        big.setContentDescription(digits.replace("", " ").trim());
        text(getString(R.string.compare_hint), 14, false);
        primaryButton(getString(R.string.digits_match), v -> {
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
        secondaryButton(getString(R.string.digits_differ), v -> io.execute(() -> {
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
            showProblem(errorText(e.code));
            return;
        }
        String profile = String.valueOf(request.get("profile_name"));
        String computer = String.valueOf(request.get("desktop_name"));
        long expiresAt = ((Long) request.get("expiry")) * 1000;
        long deadline = expiresAt + SKEW_MILLIS;
        // Listen now, so the computer can show that the phone has the request while the user decides.
        CompletableFuture<Link.Channel> connected = CompletableFuture.supplyAsync(() -> {
            try {
                operation = Operation.open(this, Link.instanceName("u", (String) request.get("req_id")));
                return operation.accept(deadline);
            } catch (Exception e) {
                throw new java.util.concurrent.CompletionException(e);
            }
        }, io);
        pending = connected;
        root.removeAllViews();
        title(getString(R.string.unlock_title, profile, computer));
        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setPadding(dp(16), dp(12), dp(16), dp(12));
        card.setBackground(rounded(color(R.color.surface), color(R.color.border), dp(12)));
        for (String line : new String[] {getString(R.string.unlock_profile, profile),
                getString(R.string.unlock_computer, computer)}) {
            TextView item = new TextView(this);
            item.setText(line);
            item.setTextColor(color(R.color.text_primary));
            item.setTextSize(TypedValue.COMPLEX_UNIT_SP, 16);
            item.setPadding(0, dp(4), 0, dp(4));
            card.addView(item);
        }
        root.addView(card, spaced(dp(8)));
        text(getString(R.string.unlock_hint), 14, false);
        primaryButton(getString(R.string.unlock_button), v -> {
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
                        pending = null; // now held as the channel
                        Map<String, Object> message = new TreeMap<>(response);
                        message.put("t", "response");
                        channel.send(message);
                        Map<String, Object> end = channel.recv(remaining(deadline));
                        if (!"ok".equals(end.get("t"))) {
                            throw new PhoneRejected(String.valueOf(end.getOrDefault("code", "bad-message")));
                        }
                        main.post(() -> showHome(getString(R.string.unlocked, profile, computer)));
                    } catch (java.util.concurrent.TimeoutException e) {
                        // Past the request's expiry the computer has stopped waiting: say so, not "unreachable".
                        boolean expired = System.currentTimeMillis() > expiresAt;
                        fail(new PhoneRejected(expired ? "expired" : "unreachable"));
                    } catch (Exception e) {
                        fail(e);
                    }
                });
            });
        });
        // Not now: nothing is sent; the computer offers its other methods.
        secondaryButton(getString(R.string.not_now), v -> showHome(null));
    }

    // -- helpers ---------------------------------------------------------------------------

    private Cipher openCipher() {
        try {
            return box.decryptCipher();
        } catch (KeyPermanentlyInvalidatedException e) {
            box.reset();
            showProblem(getString(R.string.error_keys_invalidated));
        } catch (Exception e) {
            showProblem(getString(R.string.error_generic, e.getClass().getSimpleName()));
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
            showProblem(getString(R.string.local_network_needed));
        }
    }

    private void fail(Exception e) {
        String code = e instanceof PhoneRejected ? ((PhoneRejected) e).code
                : e.getCause() instanceof PhoneRejected ? ((PhoneRejected) e.getCause()).code : e.getClass().getSimpleName();
        main.post(() -> showProblem(errorText(code)));
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
            showProblem(getString(R.string.error_generic, "save"));
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
        if (pending != null) {
            // Nothing is sent: closing tells the computer at once to offer its other methods.
            pending.thenAccept(Link.Channel::close);
            pending = null;
        }
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

    private int color(int id) {
        return getColor(id);
    }

    private void title(String value) {
        TextView view = text(value, 24, true);
        view.setTextColor(color(R.color.text_primary));
        view.setAccessibilityHeading(true);
    }

    private void heading(String value) {
        TextView view = text(value, 18, true);
        view.setTextColor(color(R.color.text_primary));
        view.setPadding(0, dp(20), 0, dp(4));
        view.setAccessibilityHeading(true);
    }

    private TextView text(String value, int sp, boolean bold) {
        TextView view = new TextView(this);
        view.setText(value);
        view.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp);
        view.setTextColor(color(R.color.text_secondary));
        if (bold) {
            view.setTypeface(view.getTypeface(), Typeface.BOLD);
        }
        view.setPadding(0, dp(8), 0, dp(8));
        root.addView(view);
        return view;
    }

    /** A notice above the screen's content: tinted red for a problem, mint for news. */
    private void notice(String message, boolean problem) {
        TextView view = new TextView(this);
        view.setText(message);
        view.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15);
        view.setTextColor(color(problem ? R.color.critical_text : R.color.text_primary));
        view.setPadding(dp(16), dp(12), dp(16), dp(12));
        view.setBackground(rounded(color(problem ? R.color.critical_tint : R.color.accent_tint), 0, dp(12)));
        view.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        root.addView(view, spaced(dp(8)));
    }

    private void footer() {
        TextView view = text(getString(R.string.footer, BuildConfig.VERSION_NAME), 12, false);
        view.setTextColor(color(R.color.text_muted));
        view.setPadding(0, dp(32), 0, dp(8));
    }

    private void primaryButton(String label, View.OnClickListener listener) {
        button(label, listener, true);
    }

    private void secondaryButton(String label, View.OnClickListener listener) {
        button(label, listener, false);
    }

    private void button(String label, View.OnClickListener listener, boolean primary) {
        Button button = styled(new Button(this), primary);
        button.setText(label);
        button.setOnClickListener(listener);
        LinearLayout.LayoutParams params = spaced(dp(12));
        params.height = dp(52);
        root.addView(button, params);
    }

    /** Primary: filled with the brand accent. Secondary: outlined. Both with the system's ripple. */
    private Button styled(Button button, boolean primary) {
        button.setAllCaps(false);
        button.setTextSize(TypedValue.COMPLEX_UNIT_SP, 16);
        button.setStateListAnimator(null);
        button.setTextColor(color(primary ? R.color.on_accent : R.color.text_primary));
        GradientDrawable shape = primary
                ? rounded(color(R.color.accent), 0, dp(26))
                : rounded(0x00000000, color(R.color.control), dp(26));
        button.setBackground(new RippleDrawable(ColorStateList.valueOf(0x33808080), shape, null));
        button.setPadding(dp(20), 0, dp(20), 0);
        return button;
    }

    private GradientDrawable rounded(int fill, int stroke, int radius) {
        GradientDrawable shape = new GradientDrawable();
        shape.setColor(fill);
        shape.setCornerRadius(radius);
        if (stroke != 0) {
            shape.setStroke(dp(1), stroke);
        }
        return shape;
    }

    private LinearLayout.LayoutParams spaced(int top) {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        params.topMargin = top;
        return params;
    }
}
