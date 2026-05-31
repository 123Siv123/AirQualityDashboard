(function () {
  const SW_URL = "/sw.js";
  let deferredInstall = null;

  function registerServiceWorker() {
    if (!("serviceWorker" in navigator)) {
      return;
    }
    navigator.serviceWorker
      .register(SW_URL, { scope: "/" })
      .catch(function (err) {
        console.warn("Service worker registration failed", err);
      });
  }

  function showInstallBar() {
    const bar = document.getElementById("pwaInstallBar");
    if (!bar || bar.hidden) {
      return;
    }
    bar.hidden = false;
    bar.classList.add("pwa-install-bar--visible");
  }

  function hideInstallBar() {
    const bar = document.getElementById("pwaInstallBar");
    if (!bar) {
      return;
    }
    bar.hidden = true;
    bar.classList.remove("pwa-install-bar--visible");
  }

  window.addEventListener("beforeinstallprompt", function (e) {
    e.preventDefault();
    deferredInstall = e;
    showInstallBar();
  });

  window.addEventListener("appinstalled", function () {
    deferredInstall = null;
    hideInstallBar();
    localStorage.setItem("pwaInstalled", "1");
  });

  document.addEventListener("DOMContentLoaded", function () {
    registerServiceWorker();

    const btn = document.getElementById("pwaInstallBtn");
    const dismiss = document.getElementById("pwaInstallDismiss");

    if (btn) {
      btn.addEventListener("click", async function () {
        if (!deferredInstall) {
          return;
        }
        deferredInstall.prompt();
        await deferredInstall.userChoice;
        deferredInstall = null;
        hideInstallBar();
      });
    }

    if (dismiss) {
      dismiss.addEventListener("click", hideInstallBar);
    }

    if (window.matchMedia("(display-mode: standalone)").matches) {
      hideInstallBar();
      document.documentElement.classList.add("pwa-standalone");
    }

    const toggle = document.getElementById("navToggle");
    const links = document.getElementById("navLinks");
    if (toggle && links) {
      toggle.addEventListener("click", function () {
        const open = links.classList.toggle("nav-links--open");
        toggle.setAttribute("aria-expanded", open ? "true" : "false");
      });
      links.querySelectorAll("a").forEach(function (a) {
        a.addEventListener("click", function () {
          links.classList.remove("nav-links--open");
          toggle.setAttribute("aria-expanded", "false");
        });
      });
    }
  });
})();
