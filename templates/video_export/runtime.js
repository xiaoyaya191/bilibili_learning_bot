(function () {
  var slides = Array.from(document.querySelectorAll('.slide'));
  var total = slides.length;
  var current = 0;
  var autoTick = null;
  var autoLeft = 12;
  var reading = document.body.classList.contains('reading-mode');
  var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var element = function (id) { return document.getElementById(id); };
  var nav = document.querySelector('.nav');
  var drawer = element('chapterDrawer');
  var previousFocus = null;
  var savedPage = document.querySelector('.slide.active');
  if (savedPage) current = slides.indexOf(savedPage);
  if (!total) return;
  function icons() {
    if (window.lucide) lucide.createIcons({ attrs: { 'stroke-width': 1.6 } });
  }
  function announce(text) {
    var toast = element('exportToast');
    toast.textContent = text;
    toast.classList.add('show');
    clearTimeout(announce.timer);
    announce.timer = setTimeout(function () { toast.classList.remove('show'); }, 2200);
  }
  function counters(slide) {
    slide.querySelectorAll('[data-target]').forEach(function (counter) {
      if (counter.dataset.animated) return;
      var target = Number(counter.dataset.target);
      if (!Number.isFinite(target)) return;
      var decimals = Math.max(0, Math.min(4, Number(counter.dataset.decimals) || 0));
      var suffix = counter.dataset.suffix || '';
      var started = performance.now();
      counter.dataset.animated = 'true';
      function tick(now) {
        var elapsed = reduceMotion || document.body.dataset.motion === 'light' ? 1 : Math.min((now - started) / 1200, 1);
        counter.textContent = (target * (1 - Math.pow(1 - elapsed, 4))).toFixed(decimals) + suffix;
        if (elapsed < 1) requestAnimationFrame(tick);
      }
      requestAnimationFrame(tick);
    });
  }
  function progress() {
    var cur = current;
    var percent = ((cur+1)/total)*100;
    if (reading) {
      var maxScroll = document.documentElement.scrollHeight - window.innerHeight;
      percent = maxScroll > 0 ? Math.min(100, window.scrollY / maxScroll * 100) : 100;
    }
    element('progressFill').style.width = percent + '%';
    element('progressFill').classList.toggle('ready', percent > 0);
    element('progressFill').parentElement.setAttribute('aria-valuenow', String(Math.round(percent)));
  }
  function update(animate) {
    slides.forEach(function (slide, index) {
      var active = index === current;
      slide.classList.toggle('active', active);
      slide.classList.remove('animating');
      slide.setAttribute('aria-hidden', String(!active && !reading));
      slide.tabIndex = active || reading ? 0 : -1;
      slide.inert = !active && !reading;
    });
    var active = slides[current];
    if (!reading && animate !== false) {
      active.scrollTop = 0;
      void active.offsetWidth;
      active.classList.add('animating');
    }
    element('currentPage').textContent = current + 1;
    element('prevButton').disabled = current === 0;
    element('nextButton').disabled = current === total - 1;
    element('readingButton').setAttribute('aria-pressed', String(reading));
    element('playButton').disabled = reading || total < 2;
    document.querySelectorAll('.chapter-button').forEach(function (button, index) {
      button.setAttribute('aria-current', index === current ? 'page' : 'false');
    });
    progress();
    if (reading) slides.forEach(counters); else counters(active);
  }
  function go(index) {
    current = Math.max(0, Math.min(total - 1, index));
    autoLeft = 12;
    nav.style.setProperty('--auto-progress', '0');
    update();
    if (reading) slides[current].scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'start' });
  }
  function stopAuto() {
    clearInterval(autoTick);
    autoTick = null;
    nav.classList.remove('autoplay');
    element('playButton').setAttribute('aria-pressed', 'false');
    element('playButton').setAttribute('aria-label', '自动播放');
    element('playIcon').outerHTML = '<i data-lucide="play" id="playIcon"></i>';
    icons();
  }
  function toggleAuto() {
    if (autoTick) { stopAuto(); return; }
    if (reading) return;
    if (current === total - 1) go(0);
    autoLeft = 12;
    nav.classList.add('autoplay');
    element('playButton').setAttribute('aria-pressed', 'true');
    element('playButton').setAttribute('aria-label', '暂停自动播放');
    element('playIcon').outerHTML = '<i data-lucide="pause" id="playIcon"></i>';
    icons();
    autoTick = setInterval(function () {
      if (document.hidden || document.body.classList.contains('drawer-open')) return;
      autoLeft -= 1;
      nav.style.setProperty('--auto-progress', String(1 - autoLeft / 12));
      if (autoLeft <= 0) {
        if (current === total - 1) { stopAuto(); return; }
        go(current + 1);
      }
    }, 1000);
  }
  function setReading(on) {
    reading = on;
    stopAuto();
    document.body.classList.toggle('reading-mode', on);
    update(false);
    if (on) slides[current].scrollIntoView({ block: 'start' }); else window.scrollTo(0, 0);
    progress();
    announce(on ? '连续阅读 · 所有章节已展开' : '章节演示 · 使用左右键翻页');
  }
  function setDrawer(on) {
    if (on && !document.body.classList.contains('drawer-open')) previousFocus = document.activeElement;
    drawer.hidden = !on;
    document.body.classList.toggle('drawer-open', on);
    element('contentsButton').setAttribute('aria-expanded', String(on));
    element('slideContainer').inert = on;
    nav.inert = on;
    document.querySelector('.export-header').inert = on;
    if (on) element('closeContents').focus(); else if (previousFocus) previousFocus.focus();
  }
  function fullScreen() {
    var promise;
    if (!document.fullscreenElement) {
      if (!document.documentElement.requestFullscreen) { announce('当前浏览器不支持全屏'); return; }
      promise = document.documentElement.requestFullscreen();
    } else promise = document.exitFullscreen();
    if (promise && promise.catch) promise.catch(function () { announce('全屏请求未获浏览器允许'); });
  }
  function download() {
    var copy = document.documentElement.cloneNode(true);
    copy.querySelector('#chapterList').replaceChildren();
    copy.querySelectorAll('.slide-number[data-engine-number]').forEach(function (number) { number.remove(); });
    copy.querySelectorAll('[data-animated]').forEach(function (counter) { delete counter.dataset.animated; });
    copy.querySelector('.export-toast').classList.remove('show');
    copy.querySelector('body').classList.remove('drawer-open');
    copy.querySelector('#chapterDrawer').hidden = true;
    copy.querySelectorAll('[inert]').forEach(function (item) { item.removeAttribute('inert'); });
    var blob = new Blob(['<!doctype html>\n' + copy.outerHTML], { type: 'text/html;charset=utf-8' });
    var anchor = document.createElement('a');
    var url = URL.createObjectURL(blob);
    anchor.href = url;
    anchor.download = (document.title || 'learning-page').replace(/[\\/:*?"<>|]/g, '_') + '.html';
    anchor.click();
    setTimeout(function () { URL.revokeObjectURL(url); }, 2000);
    announce('已下载 · 可离线打开与分享');
  }
  slides.forEach(function (slide, index) {
    slide.dataset.index = index;
    var number = document.createElement('div');
    number.className = 'slide-number';
    number.dataset.engineNumber = 'true';
    number.textContent = String(index + 1).padStart(2, '0') + ' / ' + String(total).padStart(2, '0');
    slide.prepend(number);
    slide.querySelectorAll('.card,.feature-list li,.data-card').forEach(function (item, index) {
      item.style.setProperty('--stagger', Math.min(index * .09, .5) + 's');
    });
    var chapter = document.createElement('button');
    chapter.className = 'chapter-button';
    var label = document.createElement('strong');
    var order = document.createElement('span');
    order.textContent = String(index + 1).padStart(2, '0');
    label.textContent = ((slide.querySelector('.slide-title,.main-title,h1,h2') || {}).textContent || '第 ' + (index + 1) + ' 页').trim().slice(0, 100);
    chapter.append(order, label);
    chapter.onclick = function () { setDrawer(false); go(index); };
    element('chapterList').appendChild(chapter);
  });
  element('totalPages').textContent = total;
  element('prevButton').onclick = function () { go(current - 1); };
  element('nextButton').onclick = function () { go(current + 1); };
  element('playButton').onclick = toggleAuto;
  element('readingButton').onclick = function () { setReading(!reading); };
  element('fullscreenButton').onclick = fullScreen;
  element('contentsButton').onclick = function () { setDrawer(true); };
  element('closeContents').onclick = function () { setDrawer(false); };
  element('drawerBackdrop').onclick = function () { setDrawer(false); };
  element('downloadButton').onclick = download;
  element('printButton').onclick = function () { stopAuto(); setDrawer(false); window.print(); };
  function theme(dark) {
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
    element('themeToggle').innerHTML = '<i data-lucide="' + (dark ? 'sun' : 'moon') + '"></i>';
    element('themeToggle').setAttribute('aria-pressed', String(dark));
    icons();
  }
  element('themeToggle').onclick = function () {
    var dark = document.documentElement.getAttribute('data-theme') !== 'dark';
    theme(dark);
    try { localStorage.setItem('learning-studio-theme', dark ? 'dark' : 'light'); } catch (error) {}
  };
  document.addEventListener('keydown', function (event) {
    if (event.ctrlKey || event.metaKey || event.altKey || event.target.closest('input,textarea,select,[contenteditable="true"]')) return;
    if (event.key === 'Escape') { setDrawer(false); stopAuto(); return; }
    if (document.body.classList.contains('drawer-open')) {
      if (event.key === 'Tab') {
        var focusable = Array.from(drawer.querySelectorAll('button'));
        var index = focusable.indexOf(document.activeElement);
        if (event.shiftKey && index === 0) { event.preventDefault(); focusable[focusable.length - 1].focus(); }
        else if (!event.shiftKey && index === focusable.length - 1) { event.preventDefault(); focusable[0].focus(); }
      }
      return;
    }
    if (event.target.closest('button,a')) return;
    if (event.key === 'ArrowRight' || event.key === 'PageDown') { event.preventDefault(); go(current + 1); }
    else if (event.key === 'ArrowLeft' || event.key === 'PageUp') { event.preventDefault(); go(current - 1); }
    else if (event.key === ' ' && !reading) {
      event.preventDefault();
      var slide = slides[current];
      if (slide.scrollTop + slide.clientHeight < slide.scrollHeight - 8) slide.scrollBy({ top: slide.clientHeight * .7, behavior: reduceMotion ? 'auto' : 'smooth' });
      else go(current + 1);
    } else if (event.key.toLowerCase() === 'r') setReading(!reading);
    else if (event.key.toLowerCase() === 'f') fullScreen();
  });
  var startX = 0, startY = 0;
  document.addEventListener('touchstart', function (event) { startX = event.changedTouches[0].clientX; startY = event.changedTouches[0].clientY; }, { passive: true });
  document.addEventListener('touchend', function (event) {
    if (reading || document.body.classList.contains('drawer-open') || event.target.closest('button,a,pre,.table-wrap')) return;
    var deltaX = event.changedTouches[0].clientX - startX;
    var deltaY = event.changedTouches[0].clientY - startY;
    if (Math.abs(deltaX) > 60 && Math.abs(deltaX) > Math.abs(deltaY) * 1.4) go(current + (deltaX < 0 ? 1 : -1));
  }, { passive: true });
  window.addEventListener('scroll', function () {
    if (!reading) return;
    var visible = slides.reduce(function (best, slide, index) {
      return slide.getBoundingClientRect().top <= window.innerHeight * .35 ? index : best;
    }, 0);
    if (visible !== current) { current = visible; update(false); } else progress();
  }, { passive: true });
  window.addEventListener('resize', progress);
  document.addEventListener('fullscreenchange', function () {
    element('fullscreenButton').setAttribute('aria-pressed', String(Boolean(document.fullscreenElement)));
  });
  var savedDark = document.documentElement.getAttribute('data-theme') === 'dark';
  try {
    var savedTheme = localStorage.getItem('learning-studio-theme');
    if (savedTheme) savedDark = savedTheme === 'dark';
  } catch (error) {}
  theme(savedDark);
  update();
})();
