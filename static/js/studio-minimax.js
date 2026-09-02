import { getCurrentUser, getToken } from "/static/js/auth.js";
import { getErrorMessage, showToast } from "/static/js/utils.js";

const imageInput = document.getElementById("imageInput");
const imagePreview = document.getElementById("imagePreview");
const imageEmpty = document.getElementById("imageEmpty");
const imageStatus = document.getElementById("imageStatus");
const promptInput = document.getElementById("promptInput");
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
  runBtn.disabled = !imageInput.files[0];
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

bindDrop("imageDrop", imageInput);

runBtn.addEventListener("click", async () => {
  const user = await getCurrentUser();
  if (!user) {
    window.location.href = "/login?next=/studio/minimax";
    return;
  }
  const image = imageInput.files[0];
  if (!image) return;

  const body = new FormData();
  body.append("image", image);
  body.append("prompt", promptInput.value || "");
  runBtn.disabled = true;
  runBtn.textContent = "Queuing…";
  try {
    const response = await fetch("/api/jobs/minimax", {
      method: "POST",
      headers: { Authorization: `Bearer ${getToken()}` },
      body,
    });
    if (response.status === 401) {
      window.location.href = "/login?next=/studio/minimax";
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
