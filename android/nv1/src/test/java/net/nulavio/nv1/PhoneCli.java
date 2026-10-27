package net.nulavio.nv1;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.InetAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
import java.util.TreeMap;

/**
 * Test-only phone for tests/unit/test_companion_protocol.py: the Java implementation driven by the
 * Python desktop over a real socket, as the app does (listen, desktop connects, phone speaks first).
 *
 * <pre>
 *   PhoneCli new   STATE NAME
 *   PhoneCli pair  STATE QR-JSON          (prints {"port"}, then {"sas"}; reads yes/no; prints the result)
 *   PhoneCli unlock STATE QR-JSON ANSWER  (APPROVE, DECLINE...; prints {"port"}, then the result)
 * </pre>
 */
public final class PhoneCli {
    private PhoneCli() {}

    private static void say(Map<String, Object> message) {
        System.out.println(new String(Json.canonical(message), StandardCharsets.US_ASCII));
        System.out.flush();
    }

    private static Map<String, Object> of(String key, Object value) {
        Map<String, Object> m = new TreeMap<>();
        m.put(key, value);
        return m;
    }

    public static void main(String[] args) throws Exception {
        Path state = Path.of(args[1]);
        long now = System.currentTimeMillis() / 1000;
        if (args[0].equals("new")) {
            Secrets fresh = Secrets.generate();
            Map<String, Object> saved = new TreeMap<>();
            saved.put("public", Phone.create(args[2], fresh, () -> System.currentTimeMillis() / 1000).toState());
            saved.put("secrets", fresh.toJson()); // artificial test keys; the app keeps them in the Keystore
            Files.write(state, Json.canonical(saved));
            return;
        }
        Map<String, Object> saved = Json.parseObject(Files.readAllBytes(state));
        @SuppressWarnings("unchecked")
        Phone phone = Phone.fromState((Map<String, Object>) saved.get("public"), () -> System.currentTimeMillis() / 1000);
        @SuppressWarnings("unchecked")
        Secrets secrets = Secrets.fromJson((Map<String, Object>) saved.get("secrets"));
        Map<String, Object> qr = Json.parseObject(args[2]);
        try (ServerSocket server = new ServerSocket(0, 1, InetAddress.getLoopbackAddress())) {
            server.setSoTimeout(60_000);
            say(of("port", (long) server.getLocalPort()));
            Map<String, Object> request = null;
            if (args[0].equals("unlock")) {
                try {
                    phone.check(qr); // refused requests are never answered
                } catch (PhoneRejected e) {
                    say(of("rejected", e.code));
                    return;
                }
            }
            try (Socket socket = server.accept(); Link.Channel channel = new Link.Channel(socket)) {
                if (args[0].equals("pair")) {
                    Map<String, Object> hello = phone.scan(qr);
                    hello.put("t", "hello");
                    channel.send(hello);
                    Map<String, Object> accept = channel.recv(60_000);
                    String sas = phone.onAccept(accept);
                    say(of("sas", sas));
                    BufferedReader in = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
                    boolean match = "yes".equals(in.readLine());
                    Map<String, Object> answer = match ? phone.confirm(secrets) : of("t", "cancel");
                    answer.put("t", match ? "confirm" : "cancel");
                    channel.send(answer);
                    say(of("result", channel.recv(60_000)));
                } else {
                    request = phone.answer(qr, Phone.Answer.valueOf(args[3]), secrets);
                    Map<String, Object> response = new TreeMap<>(request);
                    response.put("t", "response");
                    channel.send(response);
                    say(of("result", channel.recv(60_000)));
                }
            } catch (PhoneRejected e) {
                say(of("rejected", e.code));
            }
        } finally {
            saved.put("public", phone.toState());
            saved.put("secrets", secrets.toJson());
            Files.write(state, Json.canonical(saved));
            secrets.wipe();
        }
        if (now < 0) {
            throw new IllegalStateException();
        }
    }
}
