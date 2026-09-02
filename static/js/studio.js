import { getCurrentUser, getToken } from "/static/js/auth.js";
import { getErrorMessage, showToast } from "/static/js/utils.js";

const imageInput = document.getElementById("imageInput");
const videoInput = document.getElementById("videoInput");
const imagePreview = document.getElementById("imagePreview");
const videoPreview = document.getElementById("videoPreview");
const imageEmpty = document.getElementById("imageEmpty");
const videoEmpty = document.getElementById("videoEmpty");
const imageStatus = document.getElementById("imageStatus");
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
  const hasImage = Boolean(imageInput.files[0]);
  const hasVideo = Boolean(videoInput.files[0]);
  runBtn.disabled = !(hasImage && hasVideo);
}

imageInput.addEventListener("change", () => {
  const file = imageInput.files[0];
  if (!file) return;
  imagePreview.src = URL.createObjectURL(file);
  imagePreview.classList.add("is-on");
  imageEmpty.classList.add("hidden");
  imageStatus.textContent = file.name;
  syncRunState();
});

videoInput.addEventListener("change", () => {
  const file = videoInput.files[0];
  if (!file) return;
  videoPreview.src = URL.createObjectURL(file);
  videoPreview.classList.add("is-on");
  videoEmpty.classList.add("hidden");
  videoStatus.textContent = file.name;
  syncRunState();
});

bindDrop("imageDrop", imageInput);
bindDrop("videoDrop", videoInput);

runBtn.addEventListener("click", async () => {
  const user = await getCurrentUser();
  if (!user) {
    window.location.href = "/login?next=/studio";
    return;
  }
  const image = imageInput.files[0];
  const video = videoInput.files[0];
  if (!image || !video) return;

  const token = getToken();
  const body = new FormData();
  body.append("image", image);
  body.append("video", video);

  runBtn.disabled = true;
  runBtn.textContent = "Queuing…";
  try {
    const response = await fetch("/api/jobs", {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body,
    });
    if (response.status === 401) {
      window.location.href = "/login?next=/studio";
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
