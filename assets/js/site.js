// Set ARXIV_ID (for example "2609.01234") once the paper is announced.
const ARXIV_ID = "";

// The hero clip plays the last seconds of each domain's test task, in
// this order and for this long each (see tools/build.py).
const HERO_DOMAINS = ["Domino", "Bridge", "Balloons", "Boil", "Fan"];
const HERO_SECONDS = 6;

function setUpArxivLinks() {
  document.querySelectorAll("[data-arxiv]").forEach((link) => {
    if (ARXIV_ID) {
      link.href = `https://arxiv.org/abs/${ARXIV_ID}`;
      link.removeAttribute("aria-disabled");
    } else {
      link.title = "The arXiv link will appear once the paper is announced.";
      const note = link.querySelector(".button-note");
      if (note) note.textContent = "arXiv, coming soon";
    }
  });
}

function setUpHero() {
  const video = document.getElementById("hero-video");
  const label = document.getElementById("hero-domain");
  if (!video) return;
  const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (!still) {
    video.play().catch(() => {
      // Autoplay can be refused; the poster stays up.
    });
  }
  video.addEventListener("timeupdate", () => {
    const index = Math.min(HERO_DOMAINS.length - 1,
      Math.floor(video.currentTime / HERO_SECONDS));
    if (label.textContent !== HERO_DOMAINS[index]) {
      label.textContent = HERO_DOMAINS[index];
    }
  });
}

function setUpRunVideos() {
  const select = document.getElementById("speed");
  const videos = [...document.querySelectorAll(".run-video")];
  const apply = (video) => {
    const rate = Number(select.value);
    video.defaultPlaybackRate = rate;
    video.playbackRate = rate;
  };
  select.addEventListener("change", () => videos.forEach(apply));
  videos.forEach((video) => {
    apply(video);
    video.addEventListener("loadedmetadata", () => apply(video));
    video.addEventListener("play", () => {
      apply(video);
      // Play one run at a time.
      videos.forEach((other) => { if (other !== video) other.pause(); });
    });
  });
}

function setUpCopy() {
  const button = document.getElementById("copy-bibtex");
  const source = document.getElementById("bibtex");
  button.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(source.textContent);
      button.textContent = "Copied";
    } catch (error) {
      const range = document.createRange();
      range.selectNodeContents(source);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      button.textContent = "Selected, press Ctrl+C";
    }
    setTimeout(() => { button.textContent = "Copy"; }, 2400);
  });
}

setUpArxivLinks();
setUpHero();
setUpRunVideos();
setUpCopy();
