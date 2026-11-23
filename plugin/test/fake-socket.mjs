// The socket stand-in for the plugin tests; see fake-game.mjs for the game that wires it in.

// Socket, from network.createSocket(): connect(port, host, cb), write(data): boolean, destroy(error),
// on("error" | "close"). The test plays the listener's side: accept() fires the connect callback, fail()
// fires error then close, close() fires close. write follows ScSocket.hpp at v0.5.5: on an accepted, open
// socket it sends the whole line and returns false; on a socket that was never accepted, or has failed or
// closed, it sends nothing and returns false; on a destroyed (disposed) socket it throws. `writeBehavior`
// scripts the next write once: "partial" sends the first half of the line and returns true, "throw" throws.
export class FakeSocket {
  constructor(game) {
    this.game = game;
    this.handlers = { error: [], close: [], data: [] };
    this.connectCallback = null;
    this.target = null;
    this.accepted = false;
    this.closed = false;
    this.destroyed = false;
    this.destroyArgument = undefined;
    this.writes = 0;
    // Bytes the listener holds after the last newline on this connection.
    this.pending = "";
  }

  connect(port, host, callback) {
    this.target = { port, host };
    this.connectCallback = callback;
    return this;
  }

  on(event, callback) {
    this.handlers[event].push(callback);
    return this;
  }

  write(data) {
    this.writes += 1;
    this.game.spend("socket.write");
    if (this.destroyed) throw new Error("Socket is disposed.");
    const behavior = this.game.writeBehavior;
    this.game.writeBehavior = "ok";
    if (behavior === "throw") throw new Error("fake write failure");
    if (!this.accepted || this.closed) return false;
    if (behavior === "partial") {
      this.deliver(data.slice(0, Math.floor(data.length / 2)));
      return true;
    }
    this.deliver(data);
    return false;
  }

  // The listener reads a byte stream and splits it on newlines, so a cut line runs into the next one.
  deliver(data) {
    const lines = (this.pending + data).split("\n");
    this.pending = lines.pop();
    for (const line of lines) this.game.land(line);
  }

  // The type definitions require an argument; the stand-in enforces that. As in ScSocket::destroy, closing
  // a socket that had connected raises close synchronously, before the socket is disposed.
  destroy(error) {
    if (error === undefined) {
      throw new TypeError("Socket.destroy requires an error argument");
    }
    const wasOpen = this.accepted && !this.closed;
    this.closed = true;
    this.destroyArgument = error;
    if (wasOpen) {
      for (const handler of this.handlers.close) handler(false);
    }
    this.destroyed = true;
    return this;
  }

  accept() {
    this.accepted = true;
    this.connectCallback();
  }

  fail(message = "ECONNREFUSED") {
    this.closed = true;
    for (const handler of this.handlers.error) handler(message);
    for (const handler of this.handlers.close) handler(true);
  }

  close() {
    this.closed = true;
    for (const handler of this.handlers.close) handler(false);
  }
}
