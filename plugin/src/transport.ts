// The socket to the listener. It counts as connected only after the connect callback fires, and as
// disconnected on error or close. Port 11799 belongs to the headless game server and is never used.

const LISTENER_HOST = "127.0.0.1";
const LISTENER_PORT = 8765;
const LOG_PREFIX = "[openrct2-analytics] ";

interface Transport {
    connect(): void;
    isConnected(): boolean;
    write(line: string): boolean;
    markDisconnected(reason: string): void;
    connectAttempts(): number;
}

function createTransport(timed: (fn: () => void) => void): Transport {
    let socket: Socket | null = null;
    let connected = false;
    let attempts = 0;

    // Logs only on a change of state, so an outage's repeated failed attempts log once.
    function markDisconnected(reason: string): void {
        if (connected) {
            connected = false;
            console.log(LOG_PREFIX + "disconnected: " + reason);
        }
    }

    // Replaces any old socket, and only then destroys it: in 0.5.5 destroy() raises the old socket's close
    // synchronously, and by then it is no longer current. A replaced socket's events are ignored before
    // timed(), because that close runs inside the reconnect's own timed call and would count twice.
    function connect(): void {
        const old = socket;
        const current = network.createSocket();
        socket = current;
        connected = false;
        attempts += 1;
        current.on("error", function (message: string): void {
            if (current === socket) {
                timed(function (): void { markDisconnected("error " + message); });
            }
        });
        current.on("close", function (): void {
            if (current === socket) {
                timed(function (): void { markDisconnected("closed"); });
            }
        });
        current.connect(LISTENER_PORT, LISTENER_HOST, function (): void {
            if (current === socket) {
                timed(function (): void {
                    connected = true;
                    console.log(LOG_PREFIX + "connected to " + LISTENER_HOST + ":" + LISTENER_PORT);
                });
            }
        });
        if (old !== null) {
            old.destroy({ reason: "reconnect" });
        }
    }

    // Only called while connected, and connected is set only once a socket exists.
    function write(line: string): boolean {
        return (socket as Socket).write(line);
    }

    return {
        connect: connect,
        isConnected: function (): boolean { return connected; },
        write: write,
        markDisconnected: markDisconnected,
        connectAttempts: function (): number { return attempts; }
    };
}
