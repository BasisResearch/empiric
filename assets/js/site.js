// The hero player shows each domain's test task, cut from its recorded
// run by tools/build.py, and moves on to the next domain at the end.
const SKIP_SECONDS = 5;

function clock(seconds) {
  const whole = Math.round(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

function setUpHero() {
  const player = document.getElementById("hero-player");
  if (!player) return;
  const video = document.getElementById("hero-video");
  const tabs = [...player.querySelectorAll(".player-tabs button")];
  const speeds = [...player.querySelectorAll(".player-speed button")];
  const play = document.getElementById("hero-play");
  const seek = document.getElementById("hero-seek");
  const time = document.getElementById("hero-time");
  const domain = document.getElementById("hero-domain");
  const caption = document.getElementById("hero-caption");
  const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let current = 0;
  let scrubbing = false;
  let frame = 0;
  // Chrome also fires "ended" when a paused video is seeked to its last
  // frame; only playback that runs into the end moves on.
  let ranOut = false;

  const start = () => {
    video.play().catch(() => {
      // Autoplay can be refused; the poster stays up.
    });
  };
  const toggle = () => (video.paused ? start() : video.pause());

  const show = () => {
    const length = Number.isFinite(video.duration) ? video.duration : 0;
    const at = scrubbing ? Number(seek.value) : Math.min(video.currentTime, length);
    seek.max = String(length || 1);
    if (!scrubbing) seek.value = String(at);
    seek.style.setProperty("--progress", `${length ? (at / length) * 100 : 0}%`);
    const text = `${clock(at)} / ${clock(length)}`;
    if (time.textContent !== text) time.textContent = text;
  };
  const tick = () => {
    show();
    frame = video.paused ? 0 : requestAnimationFrame(tick);
  };
  const skip = (seconds) => {
    const length = video.duration || 0;
    video.currentTime = Math.max(0, Math.min(length, video.currentTime + seconds));
    show();
  };

  const select = (index, autoplay) => {
    current = index;
    const tab = tabs[index];
    tabs.forEach((other) => other.setAttribute("aria-pressed", String(other === tab)));
    video.poster = tab.dataset.poster;
    video.src = tab.dataset.video;
    video.setAttribute("aria-label", `${tab.textContent} test task`);
    domain.textContent = tab.textContent;
    caption.textContent = tab.dataset.caption;
    player.classList.toggle("playing", !video.paused);
    show();
    if (autoplay) start();
  };

  tabs.forEach((tab, index) => tab.addEventListener("click", () => select(index, true)));
  play.addEventListener("click", toggle);
  video.addEventListener("click", toggle);
  document.getElementById("hero-back").addEventListener("click", () => skip(-SKIP_SECONDS));
  document.getElementById("hero-forward").addEventListener("click", () => skip(SKIP_SECONDS));
  const setSpeed = (button) => {
    speeds.forEach((other) => other.setAttribute("aria-pressed", String(other === button)));
    video.defaultPlaybackRate = Number(button.dataset.rate);
    video.playbackRate = video.defaultPlaybackRate;
  };
  speeds.forEach((button) => button.addEventListener("click", () => setSpeed(button)));
  setSpeed(speeds.find((button) => button.getAttribute("aria-pressed") === "true"));

  seek.addEventListener("pointerdown", () => { scrubbing = true; });
  ["pointerup", "pointercancel", "change"].forEach((name) => {
    seek.addEventListener(name, () => {
      scrubbing = false;
      show();
    });
  });
  seek.addEventListener("input", () => {
    video.currentTime = Number(seek.value);
    show();
  });
  seek.addEventListener("keydown", (event) => {
    const step = { ArrowLeft: -1, ArrowDown: -1, ArrowRight: 1, ArrowUp: 1,
      PageDown: -SKIP_SECONDS, PageUp: SKIP_SECONDS }[event.key];
    if (step === undefined) return;
    event.preventDefault();
    skip(step);
  });

  video.addEventListener("play", () => {
    ranOut = false;
    player.classList.add("playing");
    play.setAttribute("aria-label", "Pause");
    play.title = "Pause";
    if (!frame) frame = requestAnimationFrame(tick);
  });
  video.addEventListener("pause", () => {
    ranOut = video.ended;
    player.classList.remove("playing");
    play.setAttribute("aria-label", "Play");
    play.title = "Play";
    show();
  });
  ["loadedmetadata", "seeked", "timeupdate"].forEach((name) => video.addEventListener(name, show));
  video.addEventListener("ended", () => {
    if (ranOut) select((current + 1) % tabs.length, !still);
  });

  show();
  if (!still) start();
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

function setUpSmoothScroll() {
  // Smooth scrolling waits for load. The browser jumps to the address's
  // #section while the web fonts load and shift the sections above it; an
  // instant jump follows the section, and a smooth one overshoots it.
  const smooth = () => document.documentElement.classList.add("smooth-scroll");
  if (document.readyState === "complete") {
    smooth();
  } else {
    window.addEventListener("load", smooth, { once: true });
  }
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

setUpHero();
setUpRunVideos();
setUpSmoothScroll();
setUpCopy();
