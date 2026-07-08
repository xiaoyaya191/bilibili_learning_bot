function loadChromium() {
  const candidates = ['C:/Users/Administrator/AppData/Roaming/npm/node_modules/@playwright/cli/node_modules/playwright-core', 'playwright-core', '@playwright/test', '@playwright', 'playwright'];
  for (const c of candidates) {
    try { const m = require(c); const ch = m.chromium || (m.default && m.default.chromium); if (ch) return ch; } catch (e) {}
  }
  return null;
}
(async () => {
  const chromium = loadChromium();
  if (!chromium) { console.log('NO_CHROMIUM'); process.exit(1); }
  const b = await chromium.launch({ executablePath: 'C:/Users/Administrator/AppData/Local/ms-playwright/chromium-1200/chrome-win64/chrome.exe', args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-gpu'] });
  const p = await b.newPage();
  p.on('pageerror', e => console.log('PAGEERROR:', e.message));
  p.on('console', m => { if (m.type() === 'error') console.log('CONSOLE_ERR:', m.text()); });
  await p.goto('http://127.0.0.1:7860', { waitUntil: 'domcontentloaded' });
  await p.waitForTimeout(600);
  await p.fill('#agreeInput', '我同意').catch(e => console.log('agree err', e.message));
  await p.click('#confirmBtn').catch(e => console.log('confirm err', e.message));
  await p.waitForTimeout(1200);
  await p.fill('#loginUser', '11').catch(e => console.log('user err', e.message));
  await p.fill('#loginPass', 'TempPass123!').catch(e => console.log('pass err', e.message));
  await p.click('#loginBtn').catch(e => console.log('login err', e.message));
  await p.waitForTimeout(3500);
  const info = await p.evaluate(() => {
    const sc = [...document.querySelectorAll('script')].map((s, i) => ({ i, src: s.getAttribute('src') || '(inline)', len: s.textContent.length, hasNav: s.textContent.includes('function nav'), head: s.textContent.slice(0, 120) }));
    return { nav: typeof nav, rf_dash: typeof rf_dash, scripts: sc };
  }).catch(e => ({ evalErr: e.message }));
  console.log('EVAL:', JSON.stringify(info, null, 1));
  await b.close();
})();
