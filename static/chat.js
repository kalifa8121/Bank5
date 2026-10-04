let lastMessageId = 0;
let recorder = null;
let recordingChunks = [];
let recordingKind = null;

function roomName() {
  return document.getElementById("room").value.trim() || "general";
}

document.getElementById("room").addEventListener("change", () => {
  window.APP.room = roomName();
  lastMessageId = 0;
  document.getElementById("messages").innerHTML = "";
  pollMessages();
});

async function pollMessages() {
  try {
    const res = await fetch(`/api/messages?room=${encodeURIComponent(roomName())}&after=${lastMessageId}`);
    const data = await res.json();

    for (const m of data.messages) {
      renderMessage(m);
      lastMessageId = Math.max(lastMessageId, m.id);
    }
  } catch(e) {}
}

setInterval(pollMessages, 1500);
pollMessages();

async function loadUsers() {
  try {
    const res = await fetch("/api/users");
    const users = await res.json();

    const others = users.filter(
      u => Number(u.id) !== Number(window.APP.currentUserId)
    );

    document.getElementById("users").innerHTML = others.map(u =>
      `<div class="user-row">
        <span>
          ${escapeHtml(u.display_name)}
          <small>${escapeHtml(u.role)}</small>
        </span>

        <div>
          <button
            type="button"
            onclick="openCallWithUser(${u.id}, 'audio')">
            🎤
          </button>

          <button
            type="button"
            onclick="openCallWithUser(${u.id}, 'video')">
            📹
          </button>
        </div>
      </div>`
    ).join("");

  } catch(e) {
    console.error("Users loading error:", e);
  }
}
function renderMessage(m) {
  const box = document.getElementById("messages");
  const div = document.createElement("div");

  div.className =
    "message " +
    (m.sender_id === window.APP.currentUserId ? "mine" : "");

  let media = "";

  if (m.media_url) {
    if ((m.mimetype || "").startsWith("image/")) {
      media = `<img class="media-img" src="${m.media_url}" alt="photo">`;
    } else if ((m.mimetype || "").startsWith("audio/")) {
      media = `<audio controls src="${m.media_url}"></audio>`;
    } else if ((m.mimetype || "").startsWith("video/")) {
      media = `<video class="media-video" controls src="${m.media_url}"></video>`;
    } else {
      media = `<a href="${m.media_url}" target="_blank">📎 ${escapeHtml(m.kind)}</a>`;
    }
  }

  div.innerHTML =
    `<b>${escapeHtml(m.sender)}</b>
    <span class="time">${new Date(m.created_at).toLocaleTimeString()}</span>
    ${m.text ? `<div>${escapeHtml(m.text)}</div>` : ""}
    ${media}`;

  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

async function sendText(e) {
  e.preventDefault();

  const input = document.getElementById("textInput");
  const text = input.value.trim();

  if (!text) return;

  const fd = new FormData();

  fd.append("room", roomName());
  fd.append("text", text);
  fd.append("kind", "text");

  const res = await fetch("/api/messages", {
    method: "POST",
    body: fd
  });

  if (res.ok) {
    input.value = "";
  }

  pollMessages();
}

async function sendFile() {
  const input = document.getElementById("fileInput");

  if (!input.files.length) return;

  const file = input.files[0];

  const fd = new FormData();

  fd.append("room", roomName());
  fd.append("file", file);

  if (file.type.startsWith("image/")) {
    fd.append("kind", "photo");
  } else if (file.type.startsWith("audio/")) {
    fd.append("kind", "audio");
  } else if (file.type.startsWith("video/")) {
    fd.append("kind", "video");
  } else {
    fd.append("kind", "file");
  }

  const res = await fetch("/api/messages", {
    method: "POST",
    body: fd
  });

  const data = await res.json();

  if (!res.ok) {
    alert(data.error || "Upload failed");
  }

  input.value = "";
  pollMessages();
}

async function toggleRecording(kind) {
  if (recorder && recorder.state === "recording") {
    recorder.stop();
    return;
  }

  try {
    const stream = await navigator.mediaDevices.getUserMedia(
      kind === "audio"
        ? {audio:true}
        : {audio:true, video:true}
    );

    recordingChunks = [];
    recordingKind = kind;

    recorder = new MediaRecorder(stream);

    recorder.ondataavailable = e => {
      if (e.data.size) {
        recordingChunks.push(e.data);
      }
    };

    recorder.onstop = async () => {
      stream.getTracks().forEach(t => t.stop());

      const blob = new Blob(
        recordingChunks,
        {
          type:
            recorder.mimeType ||
            (kind === "audio"
              ? "audio/webm"
              : "video/webm")
        }
      );

      const fd = new FormData();

      fd.append("room", roomName());
      fd.append("kind", kind);
      fd.append(
        "file",
        blob,
        `recording-${Date.now()}.webm`
      );

      const res = await fetch("/api/messages", {
        method: "POST",
        body: fd
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        alert(data.error || "Recording upload failed");
      }

      document.getElementById("audioRecordBtn").textContent =
        "🎙️ Audio Record";

      document.getElementById("videoRecordBtn").textContent =
        "⏺️ Video Record";

      pollMessages();
    };

    recorder.start();

    if (kind === "audio") {
      document.getElementById("audioRecordBtn").textContent =
        "⏹️ Stop Audio";
    } else {
      document.getElementById("videoRecordBtn").textContent =
        "⏹️ Stop Video";
    }

  } catch (e) {
    alert("Camera/microphone hayyami. Browser permission ilaali.");
  }
}

function openCall() { 
  location.href = 
    `/call?room=${encodeURIComponent(roomName())}`; 
}

function openCallWithUser(receiverId, mode) {
  location.href =
    `/call?room=${encodeURIComponent(roomName())}` +
    `&receiver_id=${encodeURIComponent(receiverId)}` +
    `&mode=${encodeURIComponent(mode)}`;
}

function escapeHtml(s) { 
  return String(s).replace( 
    /[&<>"']/g, 
    c => ({ 
      '&':'&amp;', 
      '<':'&lt;', 
      '>':'&gt;', 
      '"':'&quot;', 
      "'":'&#039;' 
    }[c]) 
  ); 
}
