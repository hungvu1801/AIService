import { getCurrentUser, getToken } from "/static/js/auth.js";
import { getErrorMessage, showToast } from "/static/js/utils.js";

const promptInput = document.getElementById("promptInput");
const negativeInput = document.getElementById("negativeInput");
const promptStatus = document.getElementById("promptStatus");
const runBtn = document.getElementById("runBtn");

function promptPreview(text) {
  const cleaned = text.replace(/\s+/g, " ").trim();
  if (!cleaned) return "empty";
  return cleaned.length > 48 ? `${cleaned.slice(0, 48)}…` : cleaned;
}

function syncRunState() {
  const ready = Boolean(promptInput.value.trim());
  runBtn.disabled = !ready;
  promptStatus.textContent = promptPreview(promptInput.value);
}

promptInput.addEventListener("input", syncRunState);
negativeInput.addEventListener("input", syncRunState);

runBtn.addEventListener("click", async () => {
  const user = await getCurrentUser();
  if (!user) {
    window.location.href = "/login?next=/studio/wan";
    return;
  }
  const prompt = promptInput.value.trim();
  if (!prompt) return;

  const body = new FormData();
  body.append("prompt", prompt);
  body.append("negative", negativeInput.value.trim());
  runBtn.disabled = true;
  runBtn.textContent = "Queuing…";
  try {
    const response = await fetch("/api/jobs/wan", {
      method: "POST",
      headers: { Authorization: `Bearer ${getToken()}` },
      body,
    });
    if (response.status === 401) {
      window.location.href = "/login?next=/studio/wan";
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

syncRunState();
