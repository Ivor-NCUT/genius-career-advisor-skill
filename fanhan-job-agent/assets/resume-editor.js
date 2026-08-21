/**
 * Local-only resume editor: restore plain-text edits and export the current DOM as PDF.
 */
(function (root, factory) {
  const api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.FanhanResumeEditor = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function (root) {
  'use strict';

  function install(options) {
    options = options || {};
    const doc = options.document || document;
    const main = doc.querySelector('[data-resume-content]');
    const button = doc.querySelector('[data-export-pdf]');
    const download = doc.querySelector('[data-download-pdf]');
    const status = doc.querySelector('[data-editor-status]');
    if (!main || !button || !download) throw new Error('resume editor elements missing');

    const storage = options.storage === undefined ? localStorageOrNull() : options.storage;
    const storageKey = `fanhan-resume-draft:${doc.title}`;
    restore(main, storage, storageKey);

    let timer;
    const schedule = options.schedule || ((callback) => setTimeout(callback, 250));
    const cancel = options.cancel || clearTimeout;
    const save = () => {
      if (!storage) return setStatus(status, '自动保存不可用；仍可导出 PDF', true);
      try {
        storage.setItem(storageKey, JSON.stringify(snapshot(main)));
        setStatus(status, '已自动保存');
      } catch (_) {
        setStatus(status, '自动保存失败；请先导出 PDF', true);
      }
    };
    main.addEventListener('input', () => {
      download.hidden = true;
      download.removeAttribute('href');
      if (timer !== undefined) cancel(timer);
      timer = schedule(save);
    });

    const exportPdf = async () => {
      const pdfFactory = options.pdfFactory || root.html2pdf;
      if (typeof pdfFactory !== 'function') {
        setStatus(status, 'PDF 组件未加载，请重新打开页面', true);
        return false;
      }
      button.disabled = true;
      main.blur && main.blur();
      await Promise.resolve();
      save();
      const exportSource = cloneForExport(main);
      doc.body.classList.add('exporting');
      setStatus(status, '正在生成 PDF…');
      try {
        const pdfUrl = await pdfFactory().set({
          margin: 0,
          filename: `${safeFilename(doc.title)}.pdf`,
          image: { type: 'jpeg', quality: 0.98 },
          html2canvas: { scale: 2, backgroundColor: '#ffffff', logging: false },
          jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' },
          pagebreak: { mode: ['css', 'legacy'] },
        }).from(exportSource).outputPdf('bloburl');
        download.href = String(pdfUrl);
        download.download = `${safeFilename(doc.title)}.pdf`;
        download.hidden = false;
        setStatus(status, 'PDF 已生成，请点击“下载 PDF”，再把文件发回当前对话');
        return true;
      } catch (_) {
        setStatus(status, '导出失败，请重新打开页面后再试', true);
        return false;
      } finally {
        doc.body.classList.remove('exporting');
        button.disabled = false;
      }
    };
    button.addEventListener('click', exportPdf);
    return { exportPdf, save, storageKey };
  }

  function cloneForExport(main) {
    const clone = main.cloneNode(true);
    clone.removeAttribute && clone.removeAttribute('contenteditable');
    Array.from(clone.querySelectorAll ? clone.querySelectorAll('[contenteditable]') : [])
      .forEach((element) => element.removeAttribute('contenteditable'));
    return clone;
  }

  function snapshot(main) {
    // ponytail: drafts preserve the fixed resume section model; add sanitized rich HTML only if layout editing becomes a real need.
    return {
      version: 1,
      sections: Array.from(main.querySelectorAll('section')).map((section) => ({
        heading: text(section.querySelector('h2')),
        content: renderedText(section.querySelector('p')),
      })),
    };
  }

  function restore(main, storage, key) {
    if (!storage) return false;
    try {
      const draft = JSON.parse(storage.getItem(key) || 'null');
      const sections = Array.from(main.querySelectorAll('section'));
      if (!draft || draft.version !== 1 || !Array.isArray(draft.sections)
          || draft.sections.length !== sections.length) return false;
      sections.forEach((section, index) => {
        const saved = draft.sections[index] || {};
        const heading = section.querySelector('h2');
        const content = section.querySelector('p');
        if (heading) heading.textContent = String(saved.heading || '');
        if (content) content.innerText = String(saved.content || '');
      });
      return true;
    } catch (_) {
      return false;
    }
  }

  function localStorageOrNull() {
    try {
      const storage = globalThis.localStorage;
      const probe = '__fanhan_resume_probe__';
      storage.setItem(probe, probe);
      storage.removeItem(probe);
      return storage;
    } catch (_) {
      return null;
    }
  }

  function text(element) {
    return element ? String(element.textContent || '') : '';
  }

  function renderedText(element) {
    return element ? String(element.innerText || element.textContent || '') : '';
  }

  function safeFilename(value) {
    return String(value || '岗位专用简历').replace(/[\\/:*?"<>|]+/g, '-').trim() || '岗位专用简历';
  }

  function setStatus(element, message, isError) {
    if (!element) return;
    element.textContent = message;
    element.dataset.state = isError ? 'error' : 'ok';
  }

  async function selfTest() {
    const assert = require('node:assert/strict');
    const events = {};
    const heading = { textContent: '旧标题' };
    const paragraph = { textContent: '旧内容', innerText: '旧内容' };
    const section = { querySelector: (selector) => selector === 'h2' ? heading : paragraph };
    const main = {
      querySelectorAll: () => [section],
      addEventListener: (name, handler) => { events[name] = handler; },
      blur: () => {},
      cloneNode: () => ({
        textContent: paragraph.innerText,
        removeAttribute: () => {},
        querySelectorAll: () => [],
      }),
    };
    const button = {
      disabled: false,
      addEventListener: (name, handler) => { events[name] = handler; },
    };
    const status = { textContent: '', dataset: {} };
    const download = {
      hidden: true,
      href: '',
      download: '',
      removeAttribute: (name) => { if (name === 'href') download.href = ''; },
    };
    const classes = new Set();
    const document = {
      title: '测试简历',
      body: { classList: { add: (name) => classes.add(name), remove: (name) => classes.delete(name) } },
      querySelector: (selector) => ({
        '[data-resume-content]': main,
        '[data-export-pdf]': button,
        '[data-download-pdf]': download,
        '[data-editor-status]': status,
      }[selector]),
    };
    const values = new Map();
    const storage = {
      getItem: (key) => values.get(key) || null,
      setItem: (key, value) => values.set(key, value),
    };
    let pdfSource;
    const worker = {
      set: () => worker,
      from: (source) => { pdfSource = source; return worker; },
      outputPdf: async (type) => {
        assert.equal(type, 'bloburl');
        return 'blob:resume-pdf';
      },
    };
    const editor = install({
      document, storage, pdfFactory: () => worker,
      schedule: (callback) => { callback(); return 1; }, cancel: () => {},
    });
    paragraph.innerText = '修改后的内容';
    events.input();
    assert.equal(JSON.parse(values.get(editor.storageKey)).sections[0].content, '修改后的内容');
    assert.equal(await events.click(), true);
    assert.notEqual(pdfSource, main);
    assert.equal(pdfSource.textContent, '修改后的内容');
    assert.equal(download.href, 'blob:resume-pdf');
    assert.equal(download.download, '测试简历.pdf');
    assert.equal(download.hidden, false);
    assert.equal(status.textContent, 'PDF 已生成，请点击“下载 PDF”，再把文件发回当前对话');
    assert.equal(button.disabled, false);
    assert.equal(classes.size, 0);

    events.input();
    assert.equal(download.hidden, true);
    assert.equal(download.href, '');

    heading.textContent = '空白';
    paragraph.innerText = '空白';
    assert.equal(restore(main, storage, editor.storageKey), true);
    assert.equal(paragraph.innerText, '修改后的内容');
  }

  return { cloneForExport, install, restore, selfTest, snapshot };
}));

if (typeof module === 'object' && module.exports && require.main === module) {
  module.exports.selfTest().then(
    () => process.stdout.write('resume-editor self-test: ok\n'),
    (error) => { process.stderr.write(`${error.stack || error}\n`); process.exitCode = 1; },
  );
}
