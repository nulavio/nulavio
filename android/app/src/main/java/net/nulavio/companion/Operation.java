package net.nulavio.companion;

import android.content.Context;
import android.net.nsd.NsdManager;
import android.net.nsd.NsdServiceInfo;
import java.io.IOException;
import java.net.ServerSocket;
import java.net.Socket;
import java.net.SocketTimeoutException;
import net.nulavio.nv1.Link;
import net.nulavio.nv1.PhoneRejected;

/**
 * One pairing or unlock on the local network (ADR 0005, transport amendment): a listening socket
 * for this operation only, announced over mDNS under the operation's name, closed when it ends.
 */
final class Operation implements AutoCloseable {
    private final ServerSocket server;
    private final NsdManager nsd;
    private final NsdManager.RegistrationListener listener;

    private Operation(Context context, String instanceName) throws IOException {
        server = new ServerSocket(0, 1);
        nsd = context.getSystemService(NsdManager.class);
        NsdServiceInfo info = new NsdServiceInfo();
        info.setServiceName(instanceName);
        info.setServiceType(Link.SERVICE_TYPE);
        info.setPort(server.getLocalPort());
        listener = new NsdManager.RegistrationListener() {
            @Override public void onRegistrationFailed(NsdServiceInfo s, int error) {}
            @Override public void onUnregistrationFailed(NsdServiceInfo s, int error) {}
            @Override public void onServiceRegistered(NsdServiceInfo s) {}
            @Override public void onServiceUnregistered(NsdServiceInfo s) {}
        };
        nsd.registerService(info, NsdManager.PROTOCOL_DNS_SD, listener);
        if (BuildConfig.DEBUG) {
            // Test driver only (emulator behind NAT): which port to forward. Release builds log nothing.
            android.util.Log.i("nv1", "listening " + server.getLocalPort() + " " + instanceName);
        }
    }

    static Operation open(Context context, String instanceName) throws IOException {
        return new Operation(context, instanceName);
    }

    /** The computer's connection, or "unreachable" when it does not come before the deadline. */
    Link.Channel accept(long deadlineMillis) throws IOException {
        int wait = (int) Math.max(1, deadlineMillis - System.currentTimeMillis());
        server.setSoTimeout(wait);
        try {
            Socket socket = server.accept();
            return new Link.Channel(socket);
        } catch (SocketTimeoutException e) {
            throw new PhoneRejected("unreachable");
        }
    }

    @Override
    public void close() {
        try {
            nsd.unregisterService(listener);
        } catch (IllegalArgumentException ignored) {
            // never registered
        }
        try {
            server.close();
        } catch (IOException ignored) {
            // closing anyway
        }
    }
}
