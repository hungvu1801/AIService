import { getCurrentUser, getToken } from "/static/js/auth.js";
import { escapeHtml, formatDate, getErrorMessage, showToast } from "/static/js/utils.js";

const empty = document.getElementById("jobsEmpty");
const list = document.getElementById("jobsList");

function toolLabel(tool) {
  if (tool === "animatediff") return "Pixel Art Video";
  if (tool === "motion_transfer") return "Motion Transfer";
  if (tool === "minimax") return "MiniMax H3";
  if (tool === "wan_t2v") return "Wan T2V";
  return tool.replaceAll("_", " ");
}

function badgeClass(status) {
  if (status === "done") return "badge-done";
  if (status === "processing" || status === "queued") return "badge-lime";
  if (status === "failed" || status === "cancelled") return "badge-failed";
  return "badge-muted";
}

function actions(job) {
  const bits = [];
  if (job.has_output) {
    bits.push(`<button class="btn btn-primary" data-download="${escapeHtml(job.id)}">Download</button>`);
  }
  if (job.status === "queued" || job.status === "processing") {
    bits.push(`<button class="btn btn-ghost" data-cancel="${escapeHtml(job.id)}">Cancel</button>`);
  }
  return bits.join(" ");
}

function render(jobs) {
  if (!jobs.length) {
    empty.classList.remove("hidden");
    list.classList.add("hidden");
    list.innerHTML = "";
    return;
  }
  empty.classList.add("hidden");
  list.classList.remove("hidden");
  list.innerHTML = jobs
    .map(
      (job) => `
      <article class="job-row">
        <div class="job-thumb" aria-hidden="true"></div>
        <div>
          <h3>${escapeHtml(toolLabel(job.tool))}</h3>
          <p>${escapeHtml([job.image_name, job.video_name].filter((name) => name && name !== "-").join(" · "))}<br>
          ${formatDate(job.created_at)}${job.error ? ` · ${escapeHtml(job.error)}` : ""}</p>
        </div>
        <div class="job-actions">
          <span class="badge ${badgeClass(job.status)}">${escapeHtml(job.status)}</span>
          ${actions(job)}
        </div>
      </article>
    `,
    )
    .join("");
}

function authHeaders() {
  return { Authorization: `Bearer ${getToken()}` };
}

async function loadJobs() {
  const response = await fetch("/api/jobs", { headers: authHeaders() });
  if (response.status === 401) {
    window.location.href = "/login?next=/jobs";
    return null;
  }
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    showToast(getErrorMessage(error), "error");
    return null;
  }
  return response.json();
}

async function downloadJob(jobId) {
  const response = await fetch(`/api/jobs/${jobId}/download`, {
    headers: authHeaders(),
  });
  if (!response.ok) {
    showToast("Download is not ready.", "error");
    return;
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${jobId}.mp4`;
  link.click();
  URL.revokeObjectURL(url);
}

async function cancelJob(jobId) {
  const response = await fetch(`/api/jobs/${jobId}/cancel`, {
    method: "POST",
    headers: authHeaders(),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    showToast(getErrorMessage(error), "error");
    return;
  }
  showToast("Job cancelled.", "ok");
  const jobs = await loadJobs();
  if (jobs) render(jobs);
}

list.addEventListener("click", (event) => {
  const downloadId = event.target.closest("[data-download]")?.dataset.download;
  const cancelId = event.target.closest("[data-cancel]")?.dataset.cancel;
  if (downloadId) downloadJob(downloadId);
  if (cancelId) cancelJob(cancelId);
});

const user = await getCurrentUser();
if (!user) {
  window.location.href = "/login?next=/jobs";
} else {
  const jobs = await loadJobs();
  if (jobs) render(jobs);
  window.setInterval(async () => {
    const latest = await loadJobs();
    if (latest) render(latest);
  }, 4000);
}
