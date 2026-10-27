package net.nulavio.nv1;

/** The phone refuses a message; {@code code} is stable for the UI and tests (phone_reference.py). */
public final class PhoneRejected extends RuntimeException {
    private static final long serialVersionUID = 1L;
    public final String code;

    public PhoneRejected(String code) {
        super(code);
        this.code = code;
    }
}
