// A player shows one of several clips, picked with its tab buttons, and
// moves on to the next clip when one plays to its end. A tab's data-rate is
// the speed its clip starts at; without one the speed carries over. The
// hero's player draws its own controls, with a link that downloads the clip
// on screen; the real-robot and full-recording players use the browser's.
const SKIP_SECONDS = 5;

function clock(seconds) {
  const whole = Math.round(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

function setUpPlayer(player, { autoplay, loop }) {
  if (!player) return;
  const video = player.querySelector("video");
  const tabs = [...player.querySelectorAll(".player-tabs button")];
  const speeds = [...player.querySelectorAll(".player-speed button")];
  const name = player.querySelector(".player-name");
  const caption = player.querySelector(".player-caption");
  const learned = player.querySelector(".player-learned");
  const play = player.querySelector(".player-play");
  const seek = player.querySelector(".player-seek");
  const time = player.querySelector(".player-time");
  const download = player.querySelector(".player-download");
  const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let current = 0;
  let scrubbing = false;
  let frame = 0;
  // Chrome also fires "ended" when a paused video is seeked to its last
  // frame; only playback that runs into the end moves on.
  let ranOut = false;

  const setRate = (rate) => {
    speeds.forEach((button) => {
      button.setAttribute("aria-pressed", String(Number(button.dataset.rate) === rate));
    });
    video.defaultPlaybackRate = rate;
    video.playbackRate = rate;
  };
  const start = () => {
    video.play().catch(() => {
      // Autoplay can be refused; the poster stays up.
    });
  };

  const show = () => {
    if (!seek) return;
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

  const select = (index, autoplayNext) => {
    current = index;
    const tab = tabs[index];
    tabs.forEach((other) => other.setAttribute("aria-pressed", String(other === tab)));
    video.poster = tab.dataset.poster;
    video.src = tab.dataset.video;
    if (tab.dataset.rate) setRate(Number(tab.dataset.rate));
    name.textContent = tab.textContent;
    caption.textContent = tab.dataset.caption;
    if (learned) learned.textContent = tab.dataset.learned || "";
    if (download) {
      // The download link follows the clip on screen.
      const label = tab.textContent.trim();
      download.href = tab.dataset.video;
      download.download = `empiric-${label.toLowerCase().replace(/\s+/g, "-")}.mp4`;
      download.setAttribute("aria-label", `Download the ${label} video`);
    }
    player.classList.toggle("playing", !video.paused);
    show();
    if (autoplayNext) start();
  };
  tabs.forEach((tab, index) => tab.addEventListener("click", () => select(index, true)));

  speeds.forEach((button) => {
    button.addEventListener("click", () => setRate(Number(button.dataset.rate)));
  });
  const pressed = speeds.find((button) => button.getAttribute("aria-pressed") === "true");
  setRate(Number(tabs[current].dataset.rate || pressed.dataset.rate));

  if (play) {
    const toggle = () => (video.paused ? start() : video.pause());
    play.addEventListener("click", toggle);
    video.addEventListener("click", toggle);
    player.querySelector(".player-back").addEventListener("click", () => skip(-SKIP_SECONDS));
    player.querySelector(".player-forward").addEventListener("click", () => skip(SKIP_SECONDS));
    seek.addEventListener("pointerdown", () => { scrubbing = true; });
    ["pointerup", "pointercancel", "change"].forEach((type) => {
      seek.addEventListener(type, () => {
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
    ["loadedmetadata", "seeked", "timeupdate"].forEach((type) => video.addEventListener(type, show));
  }

  video.addEventListener("play", () => {
    ranOut = false;
    player.classList.add("playing");
    if (!play) return;
    play.setAttribute("aria-label", "Pause");
    play.title = "Pause";
    if (!frame) frame = requestAnimationFrame(tick);
  });
  video.addEventListener("pause", () => {
    ranOut = video.ended;
    player.classList.remove("playing");
    if (!play) return;
    play.setAttribute("aria-label", "Play");
    play.title = "Play";
    show();
  });
  video.addEventListener("ended", () => {
    if (!ranOut) return;
    if (current + 1 < tabs.length) select(current + 1, !still);
    else if (loop) select(0, !still);
  });

  show();
  if (autoplay && !still) start();
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

function setUpSectionNav() {
  // The navigation marks the section being read: the last one whose top has
  // passed just below the bar, or the last section once the page ends.
  const links = [...document.querySelectorAll(".nav-sections a")];
  const pairs = links
    .map((link) => [link, document.getElementById(link.getAttribute("href").slice(1))])
    .filter(([, section]) => section);
  if (!pairs.length) return;
  let queued = false;
  const update = () => {
    queued = false;
    const root = document.documentElement;
    const atEnd = window.innerHeight + window.scrollY >= root.scrollHeight - 2;
    let current = null;
    pairs.forEach(([link, section]) => {
      if (section.getBoundingClientRect().top <= 120) current = link;
    });
    if (atEnd) current = pairs[pairs.length - 1][0];
    links.forEach((link) => {
      if (link === current) link.setAttribute("aria-current", "true");
      else link.removeAttribute("aria-current");
    });
  };
  const queue = () => {
    if (queued) return;
    queued = true;
    requestAnimationFrame(update);
  };
  window.addEventListener("scroll", queue, { passive: true });
  window.addEventListener("resize", queue);
  update();
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

setUpPlayer(document.getElementById("hero-player"), { autoplay: true, loop: true });
setUpPlayer(document.getElementById("robot-player"), { autoplay: false, loop: false });
setUpPlayer(document.getElementById("runs-player"), { autoplay: false, loop: false });
setUpSmoothScroll();
setUpSectionNav();
setUpCopy();
