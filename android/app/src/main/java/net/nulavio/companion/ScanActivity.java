package net.nulavio.companion;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Bundle;
import com.google.zxing.BarcodeFormat;
import com.journeyapps.barcodescanner.DecoratedBarcodeView;
import com.journeyapps.barcodescanner.DefaultDecoderFactory;
import java.util.List;

/**
 * Reads one QR code with the camera and returns its text. The library's own CaptureActivity asks
 * for the camera through AndroidX, which this app does not ship, so the permission is asked here
 * with the platform API and only the library's view is used.
 */
public final class ScanActivity extends Activity {
    static final String EXTRA_CODE = "nv1.code";
    static final String EXTRA_CAMERA_DENIED = "nv1.camera-denied";
    private static final int CAMERA_REQUEST = 8;

    private DecoratedBarcodeView view;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        if (getActionBar() != null) {
            getActionBar().hide();
        }
        view = new DecoratedBarcodeView(this);
        view.getBarcodeView().setDecoderFactory(new DefaultDecoderFactory(List.of(BarcodeFormat.QR_CODE)));
        view.setStatusText(getString(R.string.scan_prompt));
        Insets.pad(view);
        setContentView(view);
        view.decodeSingle(result -> {
            setResult(RESULT_OK, new Intent().putExtra(EXTRA_CODE, result.getText()));
            finish();
        });
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (isFinishing()) {
            return;
        }
        if (checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
            view.resume();
        } else {
            requestPermissions(new String[] {Manifest.permission.CAMERA}, CAMERA_REQUEST);
        }
    }

    @Override
    protected void onPause() {
        view.pause();
        super.onPause();
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(code, permissions, results);
        if (code == CAMERA_REQUEST && (results.length == 0 || results[0] != PackageManager.PERMISSION_GRANTED)) {
            setResult(RESULT_CANCELED, new Intent().putExtra(EXTRA_CAMERA_DENIED, true));
            finish();
        }
        // Granted: onResume runs next and starts the camera.
    }
}
