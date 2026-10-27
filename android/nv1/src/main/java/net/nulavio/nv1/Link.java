package net.nulavio.nv1;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.Socket;
import java.net.SocketTimeoutException;
import java.nio.charset.StandardCharsets;
import java.util.Locale;
import java.util.Map;

/**
 * The local-network link (ADR 0005, transport amendment): the phone listens for one operation and
 * announces it over mDNS as {@link #SERVICE_TYPE} under {@link #instanceName}; the desktop connects;
 * canonical JSON lines, the phone speaks first.
 */
public final class Link {
    public static final String SERVICE_TYPE = "_nulavio-nv1._tcp";
    public static final int MAX_LINE = 16 * 1024;
    private static final String BASE32 = "abcdefghijklmnopqrstuvwxyz234567";

    private Link() {}

    /** nv1-p-… for a pairing (invite id), nv1-u-… for an unlock (request id): 16 base32 chars of BLAKE2b. */
    public static String instanceName(String kind, String operationId) {
        if (!kind.equals("p") && !kind.equals("u")) {
            throw new IllegalArgumentException(kind);
        }
        byte[] digest = Crypto.hash32(operationId.getBytes(StandardCharsets.UTF_8));
        StringBuilder out = new StringBuilder("nv1-").append(kind).append('-');
        int buffer = 0;
        int bits = 0;
        for (byte b : digest) {
            buffer = (buffer << 8) | (b & 0xff);
            bits += 8;
            while (bits >= 5 && out.length() < 22) {
                out.append(BASE32.charAt((buffer >>> (bits - 5)) & 31));
                bits -= 5;
            }
        }
        return out.toString().toLowerCase(Locale.ROOT);
    }

    /** One connection carrying canonical JSON lines. */
    public static final class Channel implements AutoCloseable {
        private final Socket socket;
        private final InputStream in;
        private final OutputStream out;

        public Channel(Socket socket) throws IOException {
            this.socket = socket;
            this.in = socket.getInputStream();
            this.out = socket.getOutputStream();
        }

        public void send(Map<String, Object> message) throws IOException {
            byte[] line = Json.canonical(message);
            out.write(line);
            out.write('\n');
            out.flush();
        }

        /** The next message; {@code timeoutMillis} bounds the wait. */
        public Map<String, Object> recv(int timeoutMillis) throws IOException {
            socket.setSoTimeout(timeoutMillis);
            ByteArrayOutputStream line = new ByteArrayOutputStream();
            while (true) {
                int b;
                try {
                    b = in.read();
                } catch (SocketTimeoutException e) {
                    throw new PhoneRejected("timeout");
                }
                if (b < 0) {
                    throw new PhoneRejected("closed");
                }
                if (b == '\n') {
                    break;
                }
                line.write(b);
                if (line.size() > MAX_LINE) {
                    throw new PhoneRejected("too-large");
                }
            }
            Map<String, Object> message = Json.parseObject(line.toByteArray());
            if (!(message.get("t") instanceof String)) {
                throw new PhoneRejected("bad-message");
            }
            return message;
        }

        @Override
        public void close() {
            try {
                socket.close();
            } catch (IOException ignored) {
                // closing anyway
            }
        }
    }
}
