/**
 * auth/auth.js
 * Frontend authentication management (TODO-4).
 * Manages JWT tokens in sessionStorage, login/register modal dialogs,
 * header user badges, and enables/disables chat & simulation based on auth state.
 * All texts Bahasa Indonesia. All user strings safely escaped via textContent.
 */

import {
  getAuthToken,
  getStoredUser,
  setAuthToken,
  setStoredUser,
  loginUser,
  registerUser,
  logoutUser,
  fetchMyProfile,
} from "../api.js";

let authState = {
  token: getAuthToken(),
  user: getStoredUser(),
};

export function isAuthenticated() {
  return Boolean(getAuthToken());
}

export function getCurrentUser() {
  return authState.user;
}

export function openAuthModal(defaultTab = "login", message = null) {
  const overlay = document.getElementById("auth-modal-overlay");
  const errorBanner = document.getElementById("auth-error-banner");
  const successBanner = document.getElementById("auth-success-banner");

  if (!overlay) return;

  if (errorBanner) {
    if (message) {
      errorBanner.textContent = message;
      errorBanner.style.display = "block";
    } else {
      errorBanner.textContent = "";
      errorBanner.style.display = "none";
    }
  }

  if (successBanner) {
    successBanner.textContent = "";
    successBanner.style.display = "none";
  }

  switchAuthTab(defaultTab);
  overlay.style.display = "flex";
}

export function closeAuthModal() {
  const overlay = document.getElementById("auth-modal-overlay");
  if (overlay) {
    overlay.style.display = "none";
  }
}

function switchAuthTab(tabName) {
  const loginTab = document.getElementById("tab-auth-login");
  const regTab = document.getElementById("tab-auth-register");
  const loginForm = document.getElementById("auth-login-form");
  const regForm = document.getElementById("auth-register-form");
  const errorBanner = document.getElementById("auth-error-banner");

  if (errorBanner) errorBanner.style.display = "none";

  if (tabName === "login") {
    if (loginTab) loginTab.classList.add("active");
    if (regTab) regTab.classList.remove("active");
    if (loginForm) loginForm.style.display = "flex";
    if (regForm) regForm.style.display = "none";
  } else {
    if (loginTab) loginTab.classList.remove("active");
    if (regTab) regTab.classList.add("active");
    if (loginForm) loginForm.style.display = "none";
    if (regForm) regForm.style.display = "flex";
  }
}

export function updateAuthUI() {
  const authed = isAuthenticated();
  const user = getStoredUser();

  // 1. Update Header Navigation Auth Section
  const navAuthSection = document.getElementById("nav-auth-section");
  if (navAuthSection) {
    navAuthSection.innerHTML = "";

    if (authed && user) {
      const badge = document.createElement("div");
      badge.className = "user-badge-header";

      const avatar = document.createElement("div");
      avatar.className = "user-badge-avatar";
      const initial = (user.display_name || user.email || "U").charAt(0).toUpperCase();
      avatar.textContent = initial;

      const nameSpan = document.createElement("span");
      nameSpan.className = "user-badge-name";
      nameSpan.textContent = user.display_name || user.email;

      const logoutBtn = document.createElement("button");
      logoutBtn.className = "btn-nav-logout";
      logoutBtn.id = "btn-logout";
      logoutBtn.textContent = "Keluar";
      logoutBtn.addEventListener("click", handleLogout);

      badge.appendChild(avatar);
      badge.appendChild(nameSpan);
      badge.appendChild(logoutBtn);
      navAuthSection.appendChild(badge);
    } else {
      const loginBtn = document.createElement("button");
      loginBtn.className = "btn-nav-login";
      loginBtn.id = "btn-open-login-modal";
      loginBtn.textContent = "Masuk / Daftar";
      loginBtn.addEventListener("click", () => openAuthModal("login"));
      navAuthSection.appendChild(loginBtn);
    }
  }

  // 2. Update Chat Input State
  const chatInput = document.getElementById("chat-msg-input");
  const sendBtn = document.getElementById("btn-send-chat");
  if (chatInput) {
    if (authed) {
      chatInput.disabled = false;
      chatInput.placeholder = "Ketik pertanyaan tata ruang, audit kepatuhan, atau skenario simulasi...";
    } else {
      chatInput.disabled = true;
      chatInput.placeholder = "Masuk untuk memakai fitur ini";
    }
  }
  if (sendBtn) {
    if (authed) {
      sendBtn.disabled = false;
      sendBtn.title = "Kirim pesan";
    } else {
      sendBtn.disabled = true;
      sendBtn.title = "Masuk untuk memakai fitur ini";
    }
  }

  // 3. Update Simulation Run Button State
  const simRunBtn = document.getElementById("btn-run-simulation");
  if (simRunBtn) {
    if (authed) {
      simRunBtn.textContent = "⚡ Jalankan Simulasi Sandbox";
      simRunBtn.classList.remove("auth-locked");
      simRunBtn.title = "";
    } else {
      simRunBtn.textContent = "Masuk untuk memakai fitur ini";
      simRunBtn.classList.add("auth-locked");
      simRunBtn.title = "Masuk untuk memakai fitur ini";
    }
  }

  // 4. Update Chat History (Riwayat) button & retention notice
  const historyBtn = document.getElementById("btn-chat-history");
  const historyDrawer = document.getElementById("chat-history-drawer");
  const historyList = document.getElementById("chat-history-drawer-list");
  if (historyBtn) {
    historyBtn.style.display = authed ? "inline-flex" : "none";
    if (!authed) {
      historyBtn.setAttribute("aria-expanded", "false");
    }
  }
  const dock = document.getElementById("chatbot-dock");
  if (!authed) {
    if (historyDrawer) historyDrawer.style.display = "none";
    if (dock) dock.classList.remove("riwayat-open");
    if (historyList) historyList.innerHTML = "";
  }

  const noticeEl = document.getElementById("chat-privacy-notice");
  if (noticeEl) {
    const days = user?.limits?.chat_log_retention_days;
    const displayDays = typeof days === "number" && days >= 0 ? days : 90;
    noticeEl.textContent = `Pertanyaan dan jawaban disimpan untuk evaluasi layanan (${displayDays} hari). Lihat atau hapus lewat Riwayat.`;
  }

  window.dispatchEvent(
    new CustomEvent("drp:auth-changed", { detail: { authenticated: authed } })
  );
}

async function handleLogout() {
  await logoutUser();
  authState.token = null;
  authState.user = null;
  updateAuthUI();
}

export function initAuth() {
  // Check session validity in background if token exists
  if (getAuthToken()) {
    fetchMyProfile()
      .then((profile) => {
        if (profile) {
          setStoredUser(profile);
          authState.user = profile;
          updateAuthUI();
        }
      })
      .catch(() => {
        // Token expired or invalid
        logoutUser();
        authState.token = null;
        authState.user = null;
        updateAuthUI();
      });
  }

  updateAuthUI();

  // Listen for unauthorized 401 events from any API call
  window.addEventListener("drp:unauthorized", () => {
    updateAuthUI();
    openAuthModal("login", "Login diperlukan untuk memakai simulasi dan asisten AI.");
  });

  // Modal event bindings
  const overlay = document.getElementById("auth-modal-overlay");
  const closeBtn = document.getElementById("btn-close-auth-modal");
  const tabLogin = document.getElementById("tab-auth-login");
  const tabRegister = document.getElementById("tab-auth-register");
  const loginForm = document.getElementById("auth-login-form");
  const registerForm = document.getElementById("auth-register-form");
  const errorBanner = document.getElementById("auth-error-banner");
  const successBanner = document.getElementById("auth-success-banner");

  if (closeBtn) closeBtn.addEventListener("click", closeAuthModal);
  if (overlay) {
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) closeAuthModal();
    });
  }

  if (tabLogin) tabLogin.addEventListener("click", () => switchAuthTab("login"));
  if (tabRegister) tabRegister.addEventListener("click", () => switchAuthTab("register"));

  // Click on locked simulation button prompts login
  const simRunBtn = document.getElementById("btn-run-simulation");
  if (simRunBtn) {
    simRunBtn.addEventListener("click", (e) => {
      if (!isAuthenticated()) {
        e.stopImmediatePropagation();
        openAuthModal("login", "Masuk untuk memakai fitur ini");
      }
    }, true);
  }

  // Click on chat bar when logged out prompts login
  const chatInput = document.getElementById("chat-msg-input");
  if (chatInput) {
    chatInput.parentElement.addEventListener("click", () => {
      if (!isAuthenticated()) {
        openAuthModal("login", "Masuk untuk memakai fitur ini");
      }
    });
  }

  // Handle Login submission
  if (loginForm) {
    loginForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const emailInput = document.getElementById("login-email");
      const passInput = document.getElementById("login-password");
      const submitBtn = document.getElementById("btn-submit-login");

      if (errorBanner) errorBanner.style.display = "none";
      if (successBanner) successBanner.style.display = "none";

      const email = emailInput?.value.trim() || "";
      const password = passInput?.value || "";

      if (!email || !password) return;

      submitBtn.disabled = true;
      submitBtn.textContent = "Memverifikasi...";

      try {
        const data = await loginUser(email, password);
        authState.token = data.access_token;
        authState.user = data.user;
        try {
          const profile = await fetchMyProfile();
          if (profile) {
            setStoredUser(profile);
            authState.user = profile;
          }
        } catch (_) {}
        updateAuthUI();
        closeAuthModal();
        if (passInput) passInput.value = "";
      } catch (err) {
        if (errorBanner) {
          errorBanner.textContent = err.message || "Email atau kata sandi salah.";
          errorBanner.style.display = "block";
        }
      } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = "Masuk";
      }
    });
  }

  // Handle Register submission
  if (registerForm) {
    registerForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const nameInput = document.getElementById("register-name");
      const emailInput = document.getElementById("register-email");
      const passInput = document.getElementById("register-password");
      const submitBtn = document.getElementById("btn-submit-register");

      if (errorBanner) errorBanner.style.display = "none";
      if (successBanner) successBanner.style.display = "none";

      const name = nameInput?.value.trim() || "";
      const email = emailInput?.value.trim() || "";
      const password = passInput?.value || "";

      if (!name || !email || !password) return;

      if (password.length < 10) {
        if (errorBanner) {
          errorBanner.textContent = "Kata sandi minimal 10 karakter.";
          errorBanner.style.display = "block";
        }
        return;
      }

      submitBtn.disabled = true;
      submitBtn.textContent = "Mendaftarkan...";

      try {
        await registerUser(email, password, name);
        // Automatically log in after registration
        const loginData = await loginUser(email, password);
        authState.token = loginData.access_token;
        authState.user = loginData.user;
        try {
          const profile = await fetchMyProfile();
          if (profile) {
            setStoredUser(profile);
            authState.user = profile;
          }
        } catch (_) {}
        updateAuthUI();
        closeAuthModal();
        if (passInput) passInput.value = "";
      } catch (err) {
        if (errorBanner) {
          errorBanner.textContent = err.message || "Gagal mendaftar.";
          errorBanner.style.display = "block";
        }
      } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = "Daftar Akun Baru";
      }
    });
  }
}
