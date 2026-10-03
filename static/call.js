let pc = null;
let localStream = null;
let pendingCandidates = [];
let callMode = null;

// Global Window Variables
const room = window.CALL ? window.CALL.room : 'general';
const userId = window.CALL ? window.CALL.userId : null;

/* ================================
   1. WEBSOCKET (SOCKET.IO) CONNECTION
================================ */

const socket = io();

socket.on("connect", () => {
  console.log("WebSocket Connected ID:", socket.id);
  socket.emit("join", { room: room, userId: userId });
});

socket.on("signal", async (data) => {
  if (!data || Number(data.sender_id) === Number(userId)) return;

  let payload = data.payload;
  if (typeof payload === "string") {
    try {
      payload = JSON.parse(payload);
    } catch (err) {
      console.error("Payload JSON parse error:", err);
    }
  }

  if (data.kind === "offer") {
    await receiveOffer(payload);
  } else if (data.kind === "answer") {
    await receiveAnswer(payload);
  } else if (data.kind === "candidate") {
    await receiveCandidate(payload);
  }
});

/* ================================
   2. WEBRTC CONFIGURATION
================================ */

const rtcConfig = {
  iceServers: [
    { urls: "stun:stun.l.google.com:19302" },
    { urls: "stun:stun1.l.google.com:19302" }
  ]
};

function sendSignal(kind, payload) {
  socket.emit("signal", {
    room: room,
    sender_id: userId,
    kind: kind,
    payload: payload
  });
}

function createPeerConnection() {
  if (pc) return pc;

  pc = new RTCPeerConnection(rtcConfig);

  const remoteVideo = document.getElementById("remoteVideo");
  const callStatus = document.getElementById("callStatus");

  pc.ontrack = (event) => {
    console.log("REMOTE TRACK RECEIVED");
    if (remoteVideo && event.streams && event.streams[0]) {
      remoteVideo.srcObject = event.streams[0];
      remoteVideo.play().catch(err => console.warn("Auto-play blocked:", err));
    }
  };

  pc.onicecandidate = (event) => {
    if (event.candidate) {
      sendSignal("candidate", event.candidate.toJSON());
    }
  };

  pc.onconnectionstatechange = () => {
    if (!callStatus) return;
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

  return pc;
}

/* ================================
   3. START / END CALL
================================ */

async function startCall(mode) {
  const localVideo = document.getElementById("localVideo");
  const callStatus = document.getElementById("callStatus");

  try {
    if (pc) return;

    callMode = mode;
    if (callStatus) callStatus.textContent = "🎤 Camera/microphone permission barbaadaa jira...";

    const constraints = mode === "audio"
      ? { audio: true, video: false }
      : { audio: true, video: true };

    localStream = await navigator.mediaDevices.getUserMedia(constraints);
    
    if (localVideo) {
      localVideo.srcObject = localStream;
      localVideo.style.display = (mode === "audio") ? "none" : "block";
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

    if (callStatus) {
      callStatus.textContent = mode === "video" ? "📹 Video Call eegamaa jira..." : "🎤 Voice Call eegamaa jira.";
    }

  } catch (error) {
    console.error("Start call error:", error);
    if (callStatus) callStatus.textContent = "❌ Camera/microphone banamuu dide: " + error.message;
  }
}

async function receiveOffer(payload) {
  const localVideo = document.getElementById("localVideo");
  const callStatus = document.getElementById("callStatus");

  try {
    if (pc && pc.remoteDescription) return;

    const mode = payload.mode || "video";
    callMode = mode;

    const constraints = mode === "audio"
      ? { audio: true, video: false }
      : { audio: true, video: true };

    if (callStatus) callStatus.textContent = "📞 Call dhufe. Permission gaafachaa jira...";

    localStream = await navigator.mediaDevices.getUserMedia(constraints);
    if (localVideo) {
      localVideo.srcObject = localStream;
      localVideo.style.display = (mode === "audio") ? "none" : "block";
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

    if (callStatus) {
      callStatus.textContent = mode === "video" ? "📹 Video Call walitti hidhamaa jira..." : "🎤 Voice Call walitti hidhamaa jira.";
    }

  } catch (error) {
    console.error("Offer error:", error);
    if (callStatus) callStatus.textContent = "❌ Offer fudhachuu dide: " + error.message;
  }
}

async function receiveAnswer(answer) {
  const callStatus = document.getElementById("callStatus");
  try {
    if (!pc || pc.remoteDescription) return;

    const remoteDescription = new RTCSessionDescription({
      type: answer.type,
      sdp: answer.sdp
    });

    await pc.setRemoteDescription(remoteDescription);
    await flushPendingCandidates();

    if (callStatus) callStatus.textContent = "🔗 Answer fudhatame. Call walitti hidhamuu jira.";
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

  const localVideo = document.getElementById("localVideo");
  const remoteVideo = document.getElementById("remoteVideo");

  if (localVideo) localVideo.srcObject = null;
  if (remoteVideo) remoteVideo.srcObject = null;

  pendingCandidates = [];
  callMode = null;

  window.location.href = "/chat";
}

/* ================================
   4. EVENT LISTENERS INITIALIZATION
================================ */

function initCallButtons() {
  const roomName = document.getElementById("roomName");
  if (roomName) roomName.textContent = room;

  const audioBtn = document.getElementById("startAudioBtn");
  const videoBtn = document.getElementById("startVideoBtn");
  const endBtn = document.getElementById("endCallBtn");

  if (audioBtn) {
    audioBtn.onclick = (e) => {
      e.preventDefault();
      startCall("audio");
    };
  }

  if (videoBtn) {
    videoBtn.onclick = (e) => {
      e.preventDefault();
      startCall("video");
    };
  }

  if (endBtn) {
    endBtn.onclick = (e) => {
      e.preventDefault();
      endCall();
    };
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initCallButtons);
} else {
  initCallButtons();
}
