let pc = null;
let localStream = null;
let lastSignalId = 0;
let polling = null;

let pendingCandidates = [];
let callMode = null;

const room = window.CALL.room;
const userId = window.CALL.userId;

const localVideo = document.getElementById("localVideo");
const remoteVideo = document.getElementById("remoteVideo");
const callStatus = document.getElementById("callStatus");
const roomName = document.getElementById("roomName");

roomName.textContent = room;

const rtcConfig = {
  iceServers: [
    {
      urls: "stun:stun.l.google.com:19302"
    },
    {
      urls: "stun:stun1.l.google.com:19302"
    }
  ]
};


/* =========================
   PEER CONNECTION
========================= */

function createPeerConnection() {

  if (pc) {
    return pc;
  }

  pc = new RTCPeerConnection(rtcConfig);

  pc.ontrack = event => {

    console.log("REMOTE TRACK RECEIVED");

    if (event.streams && event.streams[0]) {

      remoteVideo.srcObject =
        event.streams[0];

      remoteVideo.play().catch(() => {});
    }
  };


  pc.onicecandidate = async event => {

    if (event.candidate) {

      await sendSignal(
        "candidate",
        event.candidate.toJSON()
      );
    }
  };


  pc.onconnectionstatechange = () => {

    console.log(
      "Connection:",
      pc.connectionState
    );

    if (pc.connectionState === "connected") {

      callStatus.textContent =
        "✅ Call walitti hidhame.";

    } else if (
      pc.connectionState === "failed"
    ) {

      callStatus.textContent =
        "❌ Connection kufe. Network kee ilaali.";

    } else if (
      pc.connectionState === "disconnected"
    ) {

      callStatus.textContent =
        "⚠️ Connection addaan cite.";
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


/* =========================
   START CALL
========================= */

async function startCall(mode) {

  try {

    if (pc) {
      return;
    }

    callMode = mode;

    callStatus.textContent =
      "🎤 Camera/microphone permission barbaadaa jira...";


    const constraints =
      mode === "audio"
        ? {
            audio: true,
            video: false
          }
        : {
            audio: true,
            video: true
          };


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


    const offer =
      await pc.createOffer();


    await pc.setLocalDescription(
      offer
    );


    /*
      Offer keessatti mode daballa.
      Calleen video moo audio akka ta'e
      nama lammaffaaf beeksisa.
    */

    await sendSignal(
      "offer",
      {
        description: offer,
        mode: mode
      }
    );


    callStatus.textContent =
      mode === "video"
        ? "📹 Video Call eegamaa jira..."
        : "🎤 Voice Call eegamaa jira...";


    startPolling();

  } catch (error) {

    console.error(error);

    callStatus.textContent =
      "❌ Camera/microphone banamuu dide: " +
      error.message;

  }
}


/* =========================
   SIGNAL SEND
========================= */

async function sendSignal(kind, payload) {

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
            payload: payload
          })
        }
      );


    if (!response.ok) {

      console.error(
        "Signal failed:",
        response.status
      );
    }

  } catch (error) {

    console.error(
      "Signal error:",
      error
    );
  }
}


/* =========================
   POLLING START
========================= */

function startPolling() {

  if (polling) {
    return;
  }

  polling =
    setInterval(
      pollSignals,
      1000
    );

  pollSignals();
}


/* =========================
   RECEIVE SIGNAL
========================= */

async function pollSignals() {

  try {

    const response =
      await fetch(
        `/api/signals?room=${encodeURIComponent(room)}&after=${lastSignalId}`
      );


    if (!response.ok) {
      return;
    }


    const signals =
      await response.json();


    for (const signal of signals) {

      /*
        Signal ID ol ka'u.
      */

      lastSignalId =
        Math.max(
          lastSignalId,
          signal.id
        );


      /*
        Yoo backend sender_id
        erge, signal ofii keenyaa
        tuffadhu.
      */

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


      /* =====================
         OFFER
      ===================== */

      if (
        signal.kind === "offer"
      ) {

        await receiveOffer(
          payload
        );

      }


      /* =====================
         ANSWER
      ===================== */

      else if (
        signal.kind === "answer"
      ) {

        await receiveAnswer(
          payload
        );

      }


      /* =====================
         ICE
      ===================== */

      else if (
        signal.kind === "candidate"
      ) {

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


/* =========================
   RECEIVE OFFER
========================= */

async function receiveOffer(payload) {

  try {

    /*
      Offer haaraa yoo ta'e,
      peer connection uumi.
    */

    if (!pc) {

      const mode =
        payload.mode || "video";

      callMode = mode;


      const constraints =
        mode === "audio"
          ? {
              audio: true,
              video: false
            }
          : {
              audio: true,
              video: true
            };


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


      await pc.setRemoteDescription(
        payload.description
      );


      /*
        ICE candidate dursee dhufe
        yoo jiraate asitti galchi.
      */

      await flushPendingCandidates();


      const answer =
        await pc.createAnswer();


      await pc.setLocalDescription(
        answer
      );


      await sendSignal(
        "answer",
        answer
      );


      callStatus.textContent =
        mode === "video"
          ? "📹 Video Call walitti hidhamaa jira..."
          : "🎤 Voice Call walitti hidhamaa jira.";


      startPolling();

    }

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


/* =========================
   RECEIVE ANSWER
========================= */

async function receiveAnswer(answer) {

  try {

    if (
      !pc ||
      pc.currentRemoteDescription
    ) {
      return;
    }


    await pc.setRemoteDescription(
      answer
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


/* =========================
   RECEIVE ICE CANDIDATE
========================= */

async function receiveCandidate(candidate) {

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


/* =========================
   PENDING ICE
========================= */

async function flushPendingCandidates() {

  if (
    !pc ||
    !pc.remoteDescription
  ) {
    return;
  }


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


/* =========================
   PAGE LOAD
========================= */

/*
  Namni lammaffaan button
  cuqaasuu osoo hin barbaadin
  offer eeguu qaba.
*/

startPolling();


/* =========================
   END CALL
========================= */

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


  if (localVideo) {
    localVideo.srcObject = null;
  }


  if (remoteVideo) {
    remoteVideo.srcObject = null;
  }


  pendingCandidates = [];
  lastSignalId = 0;
  callMode = null;


  location.href =
    "/chat";
}
