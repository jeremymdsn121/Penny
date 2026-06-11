// ===== Mobile nav toggle =====
const navToggle = document.getElementById("navToggle");
const nav = document.getElementById("nav");

navToggle.addEventListener("click", () => {
  const open = nav.classList.toggle("is-open");
  navToggle.classList.toggle("is-open", open);
  navToggle.setAttribute("aria-expanded", String(open));
});

// Close the mobile nav after tapping a link
nav.querySelectorAll("a").forEach((link) =>
  link.addEventListener("click", () => {
    nav.classList.remove("is-open");
    navToggle.classList.remove("is-open");
    navToggle.setAttribute("aria-expanded", "false");
  })
);

// ===== Menu tabs =====
const tabs = document.querySelectorAll(".menu-tab");
const panels = document.querySelectorAll(".menu-panel");

tabs.forEach((tab) =>
  tab.addEventListener("click", () => {
    const target = tab.dataset.target;
    tabs.forEach((t) => t.classList.toggle("is-active", t === tab));
    panels.forEach((p) => p.classList.toggle("is-active", p.id === target));
  })
);

// ===== Open / closed status =====
// Hours: Mon–Fri 6:00–15:00, Sat 8:00–14:00, Sun closed
(function setOpenStatus() {
  const el = document.getElementById("openStatus");
  if (!el) return;

  const now = new Date();
  const day = now.getDay(); // 0 = Sun ... 6 = Sat
  const minutes = now.getHours() * 60 + now.getMinutes();

  let openMin = null;
  let closeMin = null;
  if (day >= 1 && day <= 5) {
    openMin = 6 * 60;
    closeMin = 15 * 60;
  } else if (day === 6) {
    openMin = 8 * 60;
    closeMin = 14 * 60;
  }

  const isOpen = openMin !== null && minutes >= openMin && minutes < closeMin;
  const dot = document.querySelector(".hero-hours .dot");

  if (isOpen) {
    el.textContent = "Open now · closes " + (closeMin === 15 * 60 ? "3pm" : "2pm");
    if (dot) dot.style.background = "#5fd07f";
  } else {
    el.textContent = "Closed now · Mon–Fri 6am–3pm, Sat 8am–2pm";
    if (dot) {
      dot.style.background = "#e8a33d";
      dot.style.boxShadow = "0 0 0 4px rgba(232,163,61,0.25)";
    }
  }
})();

// ===== Footer year =====
const yearEl = document.getElementById("year");
if (yearEl) yearEl.textContent = new Date().getFullYear();
