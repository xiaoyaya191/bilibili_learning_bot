(() => {
  async function load() {
    try {
      const response = await fetch('/api/learning/settings');
      const body = await response.json();
      if (!body.ok) throw new Error(body.message || '读取设置失败');
      const settings = body.settings;
      const provider = document.getElementById('learning-provider');
      provider.replaceChildren(...body.providers.map(identifier => {
        const option = document.createElement('option'); option.value = identifier; option.textContent = identifier; return option;
      }));
      for (const input of document.querySelectorAll('[data-learning-setting]')) {
        const [section, key] = input.dataset.learningSetting.split('.');
        if (input.type === 'checkbox') input.checked = Boolean(settings[section][key]);
        else input.value = settings[section][key] ?? '';
      }
      status('已读取当前账号设置。语义模型只读取本地缓存，不自动下载。');
    } catch (error) { status(error.message); }
  }
  function status(message) { document.getElementById('learning-status').textContent = message; }
  async function save() {
    const payload = {};
    for (const input of document.querySelectorAll('[data-learning-setting]')) {
      const [section, key] = input.dataset.learningSetting.split('.');
      payload[section] ??= {};
      payload[section][key] = input.type === 'checkbox' ? input.checked : input.type === 'number' ? Number(input.value) : input.value;
    }
    try {
      const response = await fetch('/api/learning/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      const body = await response.json();
      if (!body.ok) throw new Error(body.message || '保存失败');
      status('设置已保存，仅影响当前账号。');
    } catch (error) { status(error.message); }
  }
  async function upload(event) {
    const file = event.target.files[0];
    if (!file) return;
    const form = new FormData(); form.append('file', file);
    try {
      const response = await fetch('/api/learning/background', { method: 'POST', body: form });
      const body = await response.json();
      if (!body.ok) throw new Error(body.message || '上传失败');
      document.getElementById('learning-background-path').value = body.path;
      status('背景上传成功，点击保存设置后应用。');
    } catch (error) { status(error.message); }
  }
  async function exportImages() {
    const button = document.getElementById('learning-export-images');
    button.disabled = true; button.textContent = '正在排版并生成图片…';
    try {
      const response = await fetch('/api/learning/export-images', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: document.getElementById('learning-image-title').value, content: document.getElementById('learning-image-content').value }) });
      if (!response.ok) { const body = await response.json(); throw new Error(body.message || '导出失败'); }
      const url = URL.createObjectURL(await response.blob());
      const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'video-learning-images.zip'; anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
      status('图片已生成并下载，长内容自动分页。');
    } catch (error) { status(error.message); }
    finally { button.disabled = false; button.textContent = '导出 PNG 图片包'; }
  }
  document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('learning-save').addEventListener('click', save);
    document.getElementById('learning-reload').addEventListener('click', load);
    document.getElementById('learning-background').addEventListener('change', upload);
    document.getElementById('learning-export-images').addEventListener('click', exportImages);
    document.addEventListener('click', event => {
      if (event.target.closest('[data-pg="learning-tools"]')) load();
    });
    load();
  });
})();
