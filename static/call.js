let pc = null;
let localStream = null;
let pendingCandidates = [];
let callMode = null;

const room = window.CALL.room;
const userId = window.CALL.userId;

const localVideo = document.getElementById("localVideo");
const remoteVideo = document.getElementById("remoteVideo");
const callStatus = document.getElementById("callStatus");
const roomName = document.getElementById("roomName");

if (roomName) {
  roomName.textContent = room;
}

/* ================================
   1. WEBSOCKET (SOCKET.IO) CONNECTION
================================ */

const socket = io();

socket.on("connect", () => {
  console.log("WebSocket Connected ID:", socket.id);
  // Gola (room) keessatti seenuuf ergi
  socket.emit("join", { room: room, userId: userId });
});

// Signal dhufu dhaggeeffadhu
socket.on("signal", async (data) => {
  if (!data || Number(data.sender_id) === Number(userId)) return;

  const kind = data.kind;
  let payload = data.payload;

  if (typeof payload === "string") {
    try {
      payload = JSON.parse(payload);
    } catch (err) {
      console.error("Payload JSON parse error:", err);
    }
  }

  if (kind === "offer") {
    await receiveOffer(payload);
  } else if (kind === "answer") {
    await receiveAnswer(payload);
  } else if (kind === "candidate") {
    await receiveCandidate(payload);
  }
});

/* ================================
   2. WEBRTC CONFIGURATION (STUN + TURN)
================================ */

const rtcConfig = {
  iceServers: [
    { urls: "stun:stun.l.google.com:19302" },
    { urls: "stun:stun1.l.google.com:19302" },
    // TURN server Metered ykn Xirsys irraa yoo qabaatte asitti dabali
    /*
    {
      urls: "turn:global.turn.metered.ca:80",
      username: "YOUR_USERNAME",
      credential: "YOUR_PASSWORD"
    }
    */
  ]
};

/* ================================
   3. SEND SIGNAL VIA SOCKET.IO
================================ */

function sendSignal(kind, payload) {
  socket.emit("signal", {
    room: room,
    sender_id: userId,
    kind: kind,
    payload: payload
  });
}

/* ================================
   4. PEER CONNECTION CREATION
================================ */

function createPeerConnection() {
  if (pc) return pc;

  pc = new RTCPeerConnection(rtcConfig);

  pc.ontrack = (event) => {
    console.log("REMOTE TRACK RECEIVED");
    if (event.streams && event.streams[0]) {
      remoteVideo.srcObject = event.streams[0];
      remoteVideo.play().catch(err => console.warn("Auto-play blocked:", err));
    }
  };

  /* ICE candidate erguu */
  pc.onicecandidate = (event) => {
    if (event.candidate) {
      sendSignal("candidate", event.candidate.toJSON());
    }
  };

  /* Connection state ilaaluu */
  pc.onconnectionstatechange = () => {
    console.log("Connection state:", pc.connectionState);

    if (pc.connectionState === "connected") {
      callStatus.textContent = "✅ Call walitti hidhame.";
    } else if (pc.connectionState === "failed") {
      callStatus.textContent = "❌ Connection kufe. Network kee ilaali.";
    } else if (pc.connectionState === "disconnected") {
      callStatus.textContent = "⚠️ Connection addaan cite.";
    } else if (pc.connectionState === "connecting") {
      callStatus.textContent = "🔄 Call walitti hidhamuu jira...";
    }
  };

  /* ICE state & Auto-Reconnect */
  pc.oniceconnectionstatechange = () => {
    console.log("ICE state:", pc.iceConnectionState);
    if (pc.iceConnectionState === "failed") {
      pc.restartIce();
    }
  };

  return pc;
}

/* ================================
   5. START CALL
================================ */

async function startCall(mode) {
  try {
    if (pc) return;

    callMode = mode;
    callStatus.textContent = "🎤 Camera/microphone permission barbaadaa jira...";

    const constraints = mode === "audio"
      ? { audio: true, video: false }
      : { audio: true, video: true };

    localStream = await navigator.mediaDevices.getUserMedia(constraints);
    localVideo.srcObject = localStream;

    if (mode === "audio") {
      localVideo.style.display = "none";
    } else {
      localVideo.style.display = "block";
    }

    createPeerConnection();

    localStream.getTracks().forEach(track => {
      pc.addTrack(track, localStream);
    });

    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);

    sendSignal("offer", {
      type: offer.type,
      sdp: offer.sdp,
      mode: mode
    });

    if (mode === "video") {
      callStatus.textContent = "📹 Video Call eegamaa jira...";
    } else {
      callStatus.textContent = "🎤 Voice Call eegamaa jira.";
    }

  } catch (error) {
    console.error("Start call error:", error);
    callStatus.textContent = "❌ Camera/microphone banamuu dide: " + error.message;
  }
}

/* ================================
   6. RECEIVE OFFER / ANSWER / CANDIDATE
================================ */

async function receiveOffer(payload) {
  try {
    if (pc && pc.remoteDescription) return;

    const mode = payload.mode || "video";
    callMode = mode;

    const constraints = mode === "audio"
      ? { audio: true, video: false }
      : { audio: true, video: true };

    callStatus.textContent = "📞 Call dhufe. Permission gaafachaa jira...";

    localStream = await navigator.mediaDevices.getUserMedia(constraints);
    localVideo.srcObject = localStream;

    if (mode === "audio") {
      localVideo.style.display = "none";
    } else {
      localVideo.style.display = "block";
    }

    createPeerConnection();

    localStream.getTracks().forEach(track => {
      pc.addTrack(track, localStream);
    });

    const remoteDescription = new RTCSessionDescription({
      type: payload.type,
      sdp: payload.sdp
    });

    await pc.setRemoteDescription(remoteDescription);
    await flushPendingCandidates();

    const answer = await pc.createAnswer();
    await pc.setLocalDescription(answer);

    sendSignal("answer", {
      type: answer.type,
      sdp: answer.sdp
    });

    if (mode === "video") {
      callStatus.textContent = "📹 Video Call walitti hidhamaa jira...";
    } else {
      callStatus.textContent = "🎤 Voice Call walitti hidhamaa jira.";
    }

  } catch (error) {
    console.error("Offer error:", error);
    callStatus.textContent = "❌ Offer fudhachuu dide: " + error.message;
  }
}

async function receiveAnswer(answer) {
  try {
    if (!pc) return;
    if (pc.currentRemoteDescription || pc.remoteDescription) return;

    const remoteDescription = new RTCSessionDescription({
      type: answer.type,
      sdp: answer.sdp
    });

    await pc.setRemoteDescription(remoteDescription);
    await flushPendingCandidates();

    callStatus.textContent = "🔗 Answer fudhatame. Call walitti hidhamuu jira.";
  } catch (error) {
    console.error("Answer error:", error);
  }
}

async function receiveCandidate(candidateData) {
  try {
    if (!candidateData || !candidateData.candidate) return;

    if (!pc || !pc.remoteDescription || !pc.remoteDescription.type) {
      pendingCandidates.push(candidateData);
      return;
    }

    const candidate = new RTCIceCandidate(candidateData);
    await pc.addIceCandidate(candidate);
  } catch (error) {
    console.error("ICE candidate error:", error);
  }
}

async function flushPendingCandidates() {
  if (!pc || !pc.remoteDescription || !pc.remoteDescription.type) return;

  while (pendingCandidates.length > 0) {
    const candidateData = pendingCandidates.shift();
    try {
      if (candidateData && candidateData.candidate) {
        const candidate = new RTCIceCandidate(candidateData);
        await pc.addIceCandidate(candidate);
      }
    } catch (error) {
      console.error("Pending ICE error:", error);
    }
  }
}

/* ================================
   7. END CALL
================================ */

function endCall() {
  if (pc) {
    pc.ontrack = null;
    pc.onicecandidate = null;
    pc.close();
    pc = null;
  }

  if (localStream) {
    localStream.getTracks().forEach(track => track.stop());
    localStream = null;
  }

  if (localVideo) localVideo.srcObject = null;
  if (remoteVideo) remoteVideo.srcObject = null;

  pendingCandidates = [];
  callMode = null;

  location.href = "/chat";
}
