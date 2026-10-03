let pc = null;
let localStream = null;
let lastSignalId = 0;
let polling = null;

const room = window.CALL.room;

document.getElementById("roomName").textContent = room;

const rtcConfig = {
  iceServers: [
    {urls: "stun:stun.l.google.com:19302"},
    {urls: "stun:stun1.l.google.com:19302"}
  ]
};

async function startCall(mode) {

  if (pc) return;

  document.getElementById("callStatus").textContent =
    "Camera/microphone permission barbaadaa jira...";

  localStream =
    await navigator.mediaDevices.getUserMedia(
      mode === "audio"
        ? {audio:true, video:false}
        : {audio:true, video:true}
    );

  document.getElementById("localVideo").srcObject =
    localStream;

  if (mode === "audio") {
    document.getElementById("localVideo").style.display =
      "none";
  }

  pc = new RTCPeerConnection(rtcConfig);

  localStream.getTracks().forEach(
    t => pc.addTrack(t, localStream)
  );

  pc.ontrack = event => {
    document.getElementById("remoteVideo").srcObject =
      event.streams[0];
  };

  pc.onicecandidate = event => {
    if (event.candidate) {
      sendSignal(
        "candidate",
        event.candidate.toJSON()
      );
    }
  };

  const offer = await pc.createOffer();

  await pc.setLocalDescription(offer);

  await sendSignal("offer", offer);

  document.getElementById("callStatus").textContent =
    "Call room keessa jira. Namni biraa seenee offer/answer ni wal jijjiiru.";

  if (!polling) {
    polling = setInterval(
      pollSignals,
      1200
    );
  }

  pollSignals();
}

async function sendSignal(kind, payload) {

  await fetch("/api/signals", {
    method:"POST",
    headers:{
      "Content-Type":"application/json"
    },
    body:JSON.stringify({
      room,
      kind,
      payload
    })
  });
}

async function pollSignals() {

  if (!pc) return;

  try {

    const res =
      await fetch(
        `/api/signals?room=${encodeURIComponent(room)}&after=${lastSignalId}`
      );

    const signals = await res.json();

    for (const s of signals) {

      lastSignalId =
        Math.max(
          lastSignalId,
          s.id
        );

      const payload =
        JSON.parse(s.payload);

      if (s.kind === "offer") {

        if (!pc.currentRemoteDescription) {

          await pc.setRemoteDescription(
            payload
          );

          const answer =
            await pc.createAnswer();

          await pc.setLocalDescription(
            answer
          );

          await sendSignal(
            "answer",
            answer
          );
        }

      } else if (s.kind === "answer") {

        if (!pc.currentRemoteDescription) {

          await pc.setRemoteDescription(
            payload
          );
        }

      } else if (s.kind === "candidate") {

        try {
          await pc.addIceCandidate(
            payload
          );
        } catch(e) {}

      }
    }

  } catch(e) {}
}

function endCall() {

  if (polling) {
    clearInterval(polling);
  }

  polling = null;

  if (pc) {
    pc.close();
  }

  if (localStream) {
    localStream
      .getTracks()
      .forEach(t => t.stop());
  }

  pc = null;
  localStream = null;

  location.href = "/chat";
}
