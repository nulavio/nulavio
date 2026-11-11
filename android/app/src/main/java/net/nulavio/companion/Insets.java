package net.nulavio.companion;

import android.view.View;
import android.view.WindowInsets;

/**
 * Apps that target Android 15 or later are drawn edge to edge: without this, the top of each
 * screen (the profile and computer an unlock request names) sits under the status bar.
 */
final class Insets {
    private Insets() {}

    static void pad(View view) {
        int left = view.getPaddingLeft();
        int top = view.getPaddingTop();
        int right = view.getPaddingRight();
        int bottom = view.getPaddingBottom();
        view.setOnApplyWindowInsetsListener((v, insets) -> {
            android.graphics.Insets bars = insets.getInsets(
                    WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout() | WindowInsets.Type.ime());
            v.setPadding(left + bars.left, top + bars.top, right + bars.right, bottom + bars.bottom);
            return WindowInsets.CONSUMED;
        });
    }
}
