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


/* ================================
   WEBRTC CONFIGURATION
================================ */

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


/* ================================
   CREATE PEER CONNECTION
================================ */

function createPeerConnection() {

  if (pc) {
    return pc;
  }

  pc = new RTCPeerConnection(rtcConfig);

  pc.ontrack = event => {

    console.log("REMOTE TRACK RECEIVED");

    if (
      event.streams &&
      event.streams[0]
    ) {

      remoteVideo.srcObject =
        event.streams[0];

      remoteVideo.play().catch(() => {});
    }
  };


  /* ICE candidate */

  pc.onicecandidate = async event => {

    if (event.candidate) {

      await sendSignal(
        "candidate",
        event.candidate.toJSON()
      );
    }
  };


  /* Connection state */

  pc.onconnectionstatechange = () => {

    console.log(
      "Connection:",
      pc.connectionState
    );

    if (
      pc.connectionState === "connected"
    ) {

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

    } else if (
      pc.connectionState === "connecting"
    ) {

      callStatus.textContent =
        "🔄 Call walitti hidhamuu jira...";
    }
  };


  /* ICE state */

  pc.oniceconnectionstatechange = () => {

    console.log(
      "ICE:",
      pc.iceConnectionState
    );
  };


  return pc;
}


/* ================================
   START CALL
================================ */

async function startCall(mode) {

  try {

    if (pc) {
      return;
    }

    callMode = mode;

    callStatus.textContent =
      "🎤 Camera/microphone permission barbaadaa jira...";


    /* Camera / microphone */

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


    /* Peer connection */

    createPeerConnection();


    /* Add local tracks */

    localStream
      .getTracks()
      .forEach(track => {

        pc.addTrack(
          track,
          localStream
        );
      });


    /* Create OFFER */

    const offer =
      await pc.createOffer();


    await pc.setLocalDescription(
      offer
    );


    /*
      OFFER keessatti
      type fi sdp qofa ergi.
    */

    await sendSignal(
      "offer",
      {
        type: offer.type,
        sdp: offer.sdp,
        mode: mode
      }
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


/* ================================
   SEND SIGNAL TO SERVER
================================ */

async function sendSignal(
  kind,
  payload
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
            payload: payload
          })
        }
      );


    if (!response.ok) {

      console.error(
        "Signal failed:",
        response.status
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


/* ================================
   START POLLING
================================ */

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


/* ================================
   POLL SIGNALS
================================ */

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


    for (
      const signal
      of signals
    ) {

      /*
        Signal ID yaada'i.
      */

      lastSignalId =
        Math.max(
          lastSignalId,
          signal.id
        );


      /*
        Signal nama ofii hin hojjetin.
      */

      if (
        signal.sender_id &&
        Number(signal.sender_id) ===
        Number(userId)
      ) {

        continue;
      }


      let payload;


      /*
        DB irraa payload
        JSON string ta'ee dhufuu danda'a.
      */

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


      /* OFFER */

      if (
        signal.kind === "offer"
      ) {

        await receiveOffer(
          payload
        );


      /* ANSWER */

      } else if (
        signal.kind === "answer"
      ) {

        await receiveAnswer(
          payload
        );


      /* ICE CANDIDATE */

      } else if (
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


/* ================================
   RECEIVE OFFER
================================ */

async function receiveOffer(
  payload
) {

  try {

    /*
      Yoo peer connection jiraate,
      offer haaraa hin fudhannu.
    */

    if (pc) {
      return;
    }


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


    /*
      Caller irraa offer dhufe.
      Amma camera/microphone bana.
    */

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


    /*
      Local tracks dabali.
    */

    localStream
      .getTracks()
      .forEach(track => {

        pc.addTrack(
          track,
          localStream
        );
      });


    /*
      IMPORTANT:
      SDP keessatti type + sdp qofa
      gara setRemoteDescription dabarsi.
    */

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


    /*
      ICE candidates dursee dhufan
      yoo jiraatan asitti dabali.
    */

    await flushPendingCandidates();


    /*
      ANSWER uumi.
    */

    const answer =
      await pc.createAnswer();


    await pc.setLocalDescription(
      answer
    );


    /*
      ANSWER sirriitti ergi.
    */

    await sendSignal(
      "answer",
      {
        type: answer.type,
        sdp: answer.sdp
      }
    );


    if (mode === "video") {

      callStatus.textContent =
        "📹 Video Call walitti hidhamaa jira...";

    } else {

      callStatus.textContent =
        "🎤 Voice Call walitti hidhamaa jira.";
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


/* ================================
   RECEIVE ANSWER
================================ */

async function receiveAnswer(
  answer
) {

  try {

    if (!pc) {
      return;
    }


    /*
      Answer duraan fudhatameera yoo ta'e
      irra deebi'anii hin kaa'an.
    */

    if (
      pc.currentRemoteDescription
    ) {
      return;
    }


    /*
      Answer keessaa
      type + sdp qofa fayyadami.
    */

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


    /*
      Pending ICE candidates.
    */

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


/* ================================
   RECEIVE ICE CANDIDATE
================================ */

async function receiveCandidate(
  candidate
) {

  try {

    /*
      Remote description hin jirre yoo ta'e,
      candidate yeroo booda fayyadamuuf kuusi.
    */

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


/* ================================
   FLUSH PENDING ICE
================================ */

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


/* ================================
   START LISTENING WHEN PAGE OPENS
================================ */

startPolling();


/* ================================
   END CALL
================================ */

function endCall() {

  /* Stop polling */

  if (polling) {

    clearInterval(
      polling
    );

    polling = null;
  }


  /* Close peer connection */

  if (pc) {

    pc.ontrack = null;
    pc.onicecandidate = null;

    pc.close();

    pc = null;
  }


  /* Stop camera/microphone */

  if (localStream) {

    localStream
      .getTracks()
      .forEach(track => {
        track.stop();
      });

    localStream = null;
  }


  /* Clear videos */

  if (localVideo) {

    localVideo.srcObject =
      null;
  }


  if (remoteVideo) {

    remoteVideo.srcObject =
      null;
  }


  /* Reset */

  pendingCandidates = [];
  lastSignalId = 0;
  callMode = null;


  /* Back to chat */

  location.href =
    "/chat";
}
