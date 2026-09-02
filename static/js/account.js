import {
  getCurrentUser,
  getToken,
  logout,
  clearUserCache,
} from "/static/js/auth.js";
import { getErrorMessage, showToast } from "/static/js/utils.js";

let currentUserId = null;

async function loadUserData() {
  const user = await getCurrentUser();
  if (!user) {
    window.location.href = "/login?next=/account";
    return;
  }

  currentUserId = user.id;
  document.getElementById("displayUsername").textContent = user.username;
  document.getElementById("displayEmail").textContent = user.email;
  document.getElementById("profileImage").src = user.image_path;
  document.getElementById("username").value = user.username;
  document.getElementById("email").value = user.email;
}

const pictureInput = document.getElementById("pictureInput");
const imagePreview = document.getElementById("imagePreview");
const uploadBtn = document.getElementById("uploadPictureBtn");
const deleteModal = document.getElementById("deleteAccountModal");

pictureInput.addEventListener("change", (event) => {
  const file = event.target.files[0];
  if (file) {
    const reader = new FileReader();
    reader.onload = (e) => {
      imagePreview.src = e.target.result;
      imagePreview.classList.add("is-on");
    };
    reader.readAsDataURL(file);
    uploadBtn.disabled = false;
  } else {
    imagePreview.classList.remove("is-on");
    uploadBtn.disabled = true;
  }
});

uploadBtn.addEventListener("click", async () => {
  const token = getToken();
  if (!token) {
    window.location.href = "/login";
    return;
  }
  const file = pictureInput.files[0];
  if (!file) return;

  const formData = new FormData();
  formData.append("file", file);
  uploadBtn.disabled = true;
  uploadBtn.textContent = "Uploading...";

  try {
    const response = await fetch(`/api/users/${currentUserId}/picture`, {
      method: "PATCH",
      headers: { Authorization: `Bearer ${token}` },
      body: formData,
    });
    if (response.status === 401) {
      window.location.href = "/login";
      return;
    }
    if (response.ok) {
      const data = await response.json();
      clearUserCache();
      document.getElementById("profileImage").src = data.image_path;
      pictureInput.value = "";
      imagePreview.classList.remove("is-on");
      showToast("Profile picture updated.", "ok");
    } else {
      const error = await response.json();
      showToast(getErrorMessage(error), "error");
    }
  } catch {
    showToast("Network error. Please try again.", "error");
  } finally {
    uploadBtn.disabled = pictureInput.files.length === 0;
    uploadBtn.textContent = "Upload";
  }
});

document.getElementById("updateProfileForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const token = getToken();
  if (!token) {
    window.location.href = "/login";
    return;
  }
  const userData = Object.fromEntries(
    new FormData(event.currentTarget).entries(),
  );
  try {
    const response = await fetch(`/api/users/${currentUserId}`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(userData),
    });
    if (response.status === 401) {
      window.location.href = "/login";
      return;
    }
    if (response.ok) {
      const data = await response.json();
      clearUserCache();
      document.getElementById("displayUsername").textContent = data.username;
      document.getElementById("displayEmail").textContent = data.email;
      showToast("Profile updated.", "ok");
    } else {
      const error = await response.json();
      showToast(getErrorMessage(error), "error");
    }
  } catch {
    showToast("Network error. Please try again.", "error");
  }
});

document.getElementById("logoutBtn").addEventListener("click", logout);

document.getElementById("openDeleteModal").addEventListener("click", () => {
  deleteModal.classList.add("is-on");
});
document.getElementById("cancelDelete").addEventListener("click", () => {
  deleteModal.classList.remove("is-on");
});

document.getElementById("confirmDeleteAccount").addEventListener("click", async () => {
  const token = getToken();
  if (!token) {
    window.location.href = "/login";
    return;
  }
  try {
    const response = await fetch(`/api/users/${currentUserId}`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}` },
    });
    if (response.status === 204) {
      localStorage.removeItem("access_token");
      window.location.href = "/";
    } else {
      const error = await response.json();
      showToast(getErrorMessage(error), "error");
    }
  } catch {
    showToast("Network error. Please try again.", "error");
  }
});

document.getElementById("changePasswordForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const token = getToken();
  if (!token) {
    window.location.href = "/login";
    return;
  }
  const currentPassword = document.getElementById("currentPassword").value;
  const newPassword = document.getElementById("newPassword").value;
  const confirmNewPassword = document.getElementById("confirmNewPassword").value;
  if (newPassword !== confirmNewPassword) {
    showToast("New passwords do not match.", "error");
    return;
  }
  const changePasswordBtn = document.getElementById("changePasswordBtn");
  changePasswordBtn.disabled = true;
  try {
    const response = await fetch("/api/users/me/password", {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        current_password: currentPassword,
        new_password: newPassword,
      }),
    });
    if (response.status === 401) {
      window.location.href = "/login";
      return;
    }
    if (response.ok) {
      event.target.reset();
      showToast("Password changed.", "ok");
    } else {
      const error = await response.json();
      showToast(getErrorMessage(error), "error");
    }
  } catch {
    showToast("Network error. Please try again.", "error");
  } finally {
    changePasswordBtn.disabled = false;
  }
});

loadUserData();
