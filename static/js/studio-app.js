import { getCurrentUser, getToken } from "/static/js/auth.js";
import { getErrorMessage, showToast } from "/static/js/utils.js";

const studio = JSON.parse(document.getElementById("studioConfig").textContent);
const imageInput = document.getElementById("imageInput");
const image2Input = document.getElementById("image2Input");
const audioInput = document.getElementById("audioInput");
const promptInput = document.getElementById("promptInput");
const extraInput = document.getElementById("extraInput");
const negativeInput = document.getElementById("negativeInput");
const runBtn = document.getElementById("runBtn");
const runSummary = document.getElementById("runSummary");

function bindDrop(zoneId, input) {
  if (!input) return;
  const zone = document.getElementById(zoneId);
  if (!zone) return;
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

function showPreview(input, previewId, emptyId) {
  if (!input) return;
  const preview = document.getElementById(previewId);
  const empty = document.getElementById(emptyId);
  input.addEventListener("change", () => {
    const file = input.files[0];
    if (!file || !preview) return;
    preview.src = URL.createObjectURL(file);
    preview.classList.add("is-on");
    empty?.classList.add("hidden");
    syncRunState();
  });
}

function requiredReady() {
  if (studio.needs_image && !imageInput?.files[0]) return false;
  if (studio.needs_image2 && !studio.image2_optional && !image2Input?.files[0]) return false;
  if (studio.needs_audio && !audioInput?.files[0]) return false;
  if (studio.needs_prompt && !studio.prompt_optional && !(promptInput?.value || "").trim()) {
    return false;
  }
  return true;
}

function syncRunState() {
  const bits = [];
  if (studio.needs_image) {
    bits.push(`Image: <strong>${imageInput?.files[0]?.name || "not selected"}</strong>`);
  }
  if (studio.needs_image2) {
    bits.push(`${studio.image2_label}: <strong>${image2Input?.files[0]?.name || "not selected"}</strong>`);
  }
  if (studio.needs_audio) {
    bits.push(`Audio: <strong>${audioInput?.files[0]?.name || "not selected"}</strong>`);
  }
  if (studio.needs_prompt) {
    const prompt = (promptInput?.value || "").trim();
    bits.push(`Prompt: <strong>${prompt ? `${prompt.length} chars` : "empty"}</strong>`);
  }
  runSummary.innerHTML = bits.join("<br>") || "Ready when the required inputs are set.";
  runBtn.disabled = !requiredReady();
}

showPreview(imageInput, "imagePreview", "imageEmpty");
showPreview(image2Input, "image2Preview", "image2Empty");
showPreview(audioInput, "audioPreview", "audioEmpty");
bindDrop("imageDrop", imageInput);
bindDrop("image2Drop", image2Input);
bindDrop("audioDrop", audioInput);
promptInput?.addEventListener("input", syncRunState);
extraInput?.addEventListener("input", syncRunState);
negativeInput?.addEventListener("input", syncRunState);
syncRunState();

runBtn.addEventListener("click", async () => {
  const user = await getCurrentUser();
  if (!user) {
    window.location.href = `/login?next=/studio/app/${studio.slug}`;
    return;
  }
  if (!requiredReady()) return;

  const body = new FormData();
  if (imageInput?.files[0]) body.append("image", imageInput.files[0]);
  if (image2Input?.files[0]) body.append("image2", image2Input.files[0]);
  if (audioInput?.files[0]) body.append("audio", audioInput.files[0]);
  if (promptInput) body.append("prompt", promptInput.value || "");
  if (negativeInput) body.append("negative", negativeInput.value || "");
  if (extraInput) body.append("extra", extraInput.value || "");

  runBtn.disabled = true;
  runBtn.textContent = "Queuing…";
  try {
    const response = await fetch(`/api/jobs/app/${studio.slug}`, {
      method: "POST",
      headers: { Authorization: `Bearer ${getToken()}` },
      body,
    });
    if (response.status === 401) {
      window.location.href = `/login?next=/studio/app/${studio.slug}`;
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
