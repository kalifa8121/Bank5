let pc = null;
let localStream = null;
let lastSignalId = 0;
let polling = null;

let pendingCandidates = [];
let callMode = null;

/* CALL INFORMATION */
const room = window.CALL.room;
const userId = window.CALL.userId;
const receiverId = window.CALL.receiverId || null;
let peerUserId = receiverId;

const localVideo = document.getElementById("localVideo");
const remoteVideo = document.getElementById("remoteVideo");
const callStatus = document.getElementById("callStatus");
const roomName = document.getElementById("roomName");

roomName.textContent = room;


/* WEBRTC CONFIGURATION */
const rtcConfig = {
  iceServers: [
    { urls: "stun:stun.l.google.com:19302" },
    { urls: "stun:stun1.l.google.com:19302" }
  ]
};


/* CREATE PEER CONNECTION */
function createPeerConnection() {

  if (pc) return pc;

  pc = new RTCPeerConnection(rtcConfig);

  pc.ontrack = event => {

    console.log("REMOTE TRACK RECEIVED");

    if (event.streams && event.streams[0]) {

      remoteVideo.srcObject = event.streams[0];

      remoteVideo.play().catch(() => {});
    }
  };


  pc.onicecandidate = async event => {

    if (event.candidate && peerUserId) {

      await sendSignal(
        "candidate",
        event.candidate.toJSON(),
        peerUserId
      );
    }
  };


  pc.onconnectionstatechange = () => {

    console.log("Connection:", pc.connectionState);

    if (pc.connectionState === "connected") {

      callStatus.textContent =
        "✅ Call walitti hidhame.";

    } else if (pc.connectionState === "failed") {

      callStatus.textContent =
        "❌ Connection kufe. Network kee ilaali.";

    } else if (pc.connectionState === "disconnected") {

      callStatus.textContent =
        "⚠️ Connection addaan cite.";

    } else if (pc.connectionState === "connecting") {

      callStatus.textContent =
        "🔄 Call walitti hidhamuu jira...";
    }
  };


  pc.oniceconnectionstatechange = () => {

    console.log(
      "ICE:",
      pc.iceConnectionState
    );
  };


  return pc;
}


/* START CALL */
async function startCall(mode) {

  try {

    if (pc) return;

    if (!peerUserId) {

      callStatus.textContent =
        "❌ Nama call gootu hin filatamne.";

      return;
    }

    callMode = mode;

    callStatus.textContent =
      "🎤 Camera/microphone permission barbaadaa jira...";


    const constraints =
      mode === "audio"
        ? { audio: true, video: false }
        : { audio: true, video: true };


    localStream =
      await navigator.mediaDevices.getUserMedia(
        constraints
      );


    localVideo.srcObject = localStream;


    if (mode === "audio") {

      localVideo.style.display = "none";

    } else {

      localVideo.style.display = "block";
    }


    createPeerConnection();


    localStream
      .getTracks()
      .forEach(track => {

        pc.addTrack(
          track,
          localStream
        );

      });


    const offer =
      await pc.createOffer();


    await pc.setLocalDescription(
      offer
    );


    console.log(
      "LOCAL OFFER:",
      offer
    );


    await sendSignal(
      "offer",
      {
        type: offer.type,
        sdp: offer.sdp,
        mode: mode
      },
      peerUserId
    );


    if (mode === "video") {

      callStatus.textContent =
        "📹 Video Call eegamaa jira...";

    } else {

      callStatus.textContent =
        "🎤 Voice Call eegamaa jira.";
    }


    startPolling();

  } catch (error) {

    console.error(
      "Start call error:",
      error
    );

    callStatus.textContent =
      "❌ Camera/microphone banamuu dide: " +
      error.message;
  }
}


/* SEND SIGNAL TO SERVER */
async function sendSignal(
  kind,
  payload,
  targetUserId = peerUserId
) {

  try {

    const response =
      await fetch(
        "/api/signals",
        {
          method: "POST",

          headers: {
            "Content-Type":
              "application/json"
          },

          body: JSON.stringify({

            room: room,

            kind: kind,

            payload: payload,

            receiver_id:
              targetUserId
          })
        }
      );


    if (!response.ok) {

      const data =
        await response
          .json()
          .catch(() => ({}));

      console.error(
        "Signal failed:",
        response.status,
        data
      );

      return false;
    }


    return true;

  } catch (error) {

    console.error(
      "Signal error:",
      error
    );

    return false;
  }
}


/* START POLLING */
function startPolling() {

  if (polling) return;

  polling =
    setInterval(
      pollSignals,
      1000
    );

  pollSignals();
}


/* POLL SIGNALS */
async function pollSignals() {

  try {

    const response =
      await fetch(
        `/api/signals?room=${encodeURIComponent(room)}&after=${lastSignalId}`
      );


    if (!response.ok) return;


    const signals =
      await response.json();


    for (const signal of signals) {

      lastSignalId =
        Math.max(
          lastSignalId,
          signal.id
        );


      if (
        signal.sender_id &&
        Number(signal.sender_id) ===
          Number(userId)
      ) {

        continue;
      }


      let payload;


      try {

        payload =
          typeof signal.payload === "string"
            ? JSON.parse(signal.payload)
            : signal.payload;

      } catch (error) {

        console.error(
          "Payload parse error:",
          error
        );

        continue;
      }


      if (signal.kind === "offer") {

        await receiveOffer(
          payload,
          signal.sender_id
        );

      } else if (signal.kind === "answer") {

        await receiveAnswer(
          payload
        );

      } else if (signal.kind === "candidate") {

        await receiveCandidate(
          payload
        );
      }
    }

  } catch (error) {

    console.error(
      "Polling error:",
      error
    );
  }
}


/* RECEIVE OFFER */
async function receiveOffer(
  payload,
  senderId
) {

  try {

    if (pc) return;


    peerUserId =
      Number(senderId);


    const mode =
      payload.mode || "video";


    callMode = mode;


    const constraints =
      mode === "audio"
        ? { audio: true, video: false }
        : { audio: true, video: true };


    callStatus.textContent =
      "📞 Call dhufe. Camera/microphone eeyyama gaafachaa jira...";


    localStream =
      await navigator.mediaDevices.getUserMedia(
        constraints
      );


    localVideo.srcObject =
      localStream;


    if (mode === "audio") {

      localVideo.style.display =
        "none";

    } else {

      localVideo.style.display =
        "block";
    }


    createPeerConnection();


    localStream
      .getTracks()
      .forEach(track => {

        pc.addTrack(
          track,
          localStream
        );
      });


    const remoteDescription = {

      type: payload.type,

      sdp: payload.sdp
    };


    console.log(
      "REMOTE OFFER:",
      remoteDescription
    );


    await pc.setRemoteDescription(
      remoteDescription
    );


    await flushPendingCandidates();


    const answer =
      await pc.createAnswer();


    await pc.setLocalDescription(
      answer
    );


    console.log(
      "LOCAL ANSWER:",
      answer
    );


    await sendSignal(
      "answer",
      {
        type: answer.type,
        sdp: answer.sdp
      },
      peerUserId
    );


    if (mode === "video") {

      callStatus.textContent =
        "📹 Video Call walitti hidhamaa jira...";

    } else {

      callStatus.textContent =
        "🎤 Voice Call walitti hidhamaa jira...";
    }


    startPolling();

  } catch (error) {

    console.error(
      "Offer error:",
      error
    );

    callStatus.textContent =
      "❌ Offer fudhachuu dide: " +
      error.message;
  }
}


/* RECEIVE ANSWER */
async function receiveAnswer(
  answer
) {

  try {

    if (!pc) return;

    if (pc.currentRemoteDescription)
      return;


    const remoteDescription = {

      type: answer.type,

      sdp: answer.sdp
    };


    console.log(
      "REMOTE ANSWER:",
      remoteDescription
    );


    await pc.setRemoteDescription(
      remoteDescription
    );


    await flushPendingCandidates();


    callStatus.textContent =
      "🔗 Answer fudhatame. Call walitti hidhamuu jira.";

  } catch (error) {

    console.error(
      "Answer error:",
      error
    );
  }
}


/* RECEIVE ICE CANDIDATE */
async function receiveCandidate(
  candidate
) {

  try {

    if (
      !pc ||
      !pc.remoteDescription
    ) {

      pendingCandidates.push(
        candidate
      );

      return;
    }


    await pc.addIceCandidate(
      candidate
    );

  } catch (error) {

    console.error(
      "ICE candidate error:",
      error
    );
  }
}


/* FLUSH PENDING ICE */
async function flushPendingCandidates() {

  if (
    !pc ||
    !pc.remoteDescription
  ) return;


  for (
    const candidate
    of pendingCandidates
  ) {

    try {

      await pc.addIceCandidate(
        candidate
      );

    } catch (error) {

      console.error(
        "Pending ICE error:",
        error
      );
    }
  }


  pendingCandidates = [];
}


/* START LISTENING WHEN PAGE OPENS */
startPolling();


/* AUTO START CALLER */
const initialMode =
  window.CALL.mode;


if (
  initialMode === "audio" ||
  initialMode === "video"
) {

  setTimeout(
    () => startCall(initialMode),
    300
  );
}


/* END CALL */
function endCall() {

  if (polling) {

    clearInterval(
      polling
    );

    polling = null;
  }


  if (pc) {

    pc.ontrack = null;

    pc.onicecandidate = null;

    pc.close();

    pc = null;
  }


  if (localStream) {

    localStream
      .getTracks()
      .forEach(track => {

        track.stop();

      });

    localStream = null;
  }


  if (localVideo)
    localVideo.srcObject = null;


  if (remoteVideo)
    remoteVideo.srcObject = null;


  pendingCandidates = [];

  lastSignalId = 0;

  callMode = null;

  peerUserId = receiverId;


  location.href = "/chat";
}
