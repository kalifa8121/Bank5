const CACHE = "hojjattoota-v1";

self.addEventListener(
  "install",
  e => self.skipWaiting()
);

self.addEventListener(
  "activate",
  e => self.clients.claim()
);

self.addEventListener(
  "fetch",
  e => {
    // Network-first:
    // live chat/calls always use the server.
  }
);
