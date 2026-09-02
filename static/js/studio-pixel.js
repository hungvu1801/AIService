import { getCurrentUser, getToken } from "/static/js/auth.js";
import { getErrorMessage, showToast } from "/static/js/utils.js";

const videoInput = document.getElementById("videoInput");
const videoPreview = document.getElementById("videoPreview");
const videoEmpty = document.getElementById("videoEmpty");
const videoStatus = document.getElementById("videoStatus");
const runBtn = document.getElementById("runBtn");

function bindDrop(zoneId, input) {
  const zone = document.getElementById(zoneId);
  zone.addEventListener("dragover", (event) => {
    event.preventDefault();
    zone.classList.add("is-over");
  });
  zone.addEventListener("dragleave", () => zone.classList.remove("is-over"));
  zone.addEventListener("drop", (event) => {
    event.preventDefault();
    zone.classList.remove("is-over");
    const file = event.dataTransfer.files[0];
    if (!file) return;
    const transfer = new DataTransfer();
    transfer.items.add(file);
    input.files = transfer.files;
    input.dispatchEvent(new Event("change"));
  });
}

function syncRunState() {
  runBtn.disabled = !videoInput.files[0];
}

videoInput.addEventListener("change", () => {
  const file = videoInput.files[0];
  if (!file) return;
  videoPreview.src = URL.createObjectURL(file);
  videoPreview.classList.add("is-on");
  videoEmpty.classList.add("hidden");
  videoStatus.textContent = file.name;
  syncRunState();
});

bindDrop("videoDrop", videoInput);

runBtn.addEventListener("click", async () => {
  const user = await getCurrentUser();
  if (!user) {
    window.location.href = "/login?next=/studio/pixel";
    return;
  }
  const video = videoInput.files[0];
  if (!video) return;

  const body = new FormData();
  body.append("video", video);
  runBtn.disabled = true;
  runBtn.textContent = "Queuing…";
  try {
    const response = await fetch("/api/jobs/animatediff", {
      method: "POST",
      headers: { Authorization: `Bearer ${getToken()}` },
      body,
    });
    if (response.status === 401) {
      window.location.href = "/login?next=/studio/pixel";
      return;
    }
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      showToast(getErrorMessage(error), "error");
      return;
    }
    window.location.href = "/jobs";
  } catch {
    showToast("Network error. Please try again.", "error");
  } finally {
    runBtn.textContent = "Run";
    syncRunState();
  }
});
