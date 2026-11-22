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
    let exportGeneration = 0;
    const schedule = options.schedule || ((callback) => setTimeout(callback, 250));
    const cancel = options.cancel || clearTimeout;
    const createObjectURL = options.createObjectURL || ((blob) => root.URL.createObjectURL(blob));
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
      exportGeneration += 1;
      bumpRevision(main);
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
      const started = exportGeneration;
      const revision = main.getAttribute ? (main.getAttribute('data-resume-revision') || '') : '';
      button.disabled = true;
      main.blur && main.blur();
      await Promise.resolve();
      save();
      const exportSource = cloneForExport(main);
      doc.body.classList.add('exporting');
      setStatus(status, '正在生成 PDF…');
      try {
        const raw = await pdfFactory().set({
          margin: 0,
          filename: `${safeFilename(doc.title)}.pdf`,
          image: { type: 'jpeg', quality: 0.98 },
          html2canvas: { scale: 2, backgroundColor: '#ffffff', logging: false },
          jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' },
          pagebreak: { mode: 'avoid-all' },
        }).from(exportSource).outputPdf('arraybuffer');
        if (started !== exportGeneration) {
          download.hidden = true;
          download.removeAttribute('href');
          setStatus(status, '导出期间内容已修改，请重新生成 PDF', true);
          return false;
        }
        const marker = `\n%FANHAN-RESUME-REVISION ${revision}\n`;
        const sourceBytes = raw instanceof ArrayBuffer ? new Uint8Array(raw) : new TextEncoder().encode(String(raw));
        const markerBytes = new TextEncoder().encode(marker);
        const payload = new Uint8Array(sourceBytes.length + markerBytes.length);
        payload.set(sourceBytes, 0);
        payload.set(markerBytes, sourceBytes.length);
        const blob = new Blob([payload], { type: 'application/pdf' });
        download.href = String(createObjectURL(blob));
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
    const fields = {};
    Array.from(main.querySelectorAll('[data-field]')).forEach((element) => {
      const name = element.getAttribute('data-field');
      if (name) fields[name] = renderedText(element);
    });
    return {
      version: 2,
      fields,
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
      if (!draft || (draft.version !== 1 && draft.version !== 2) || !Array.isArray(draft.sections)
          || draft.sections.length !== sections.length) return false;
      sections.forEach((section, index) => {
        const saved = draft.sections[index] || {};
        const heading = section.querySelector('h2');
        const content = section.querySelector('p');
        if (heading) heading.textContent = String(saved.heading || '');
        if (content) content.innerText = String(saved.content || '');
      });
      if (draft.fields && typeof draft.fields === 'object') {
        Array.from(main.querySelectorAll('[data-field]')).forEach((element) => {
          const name = element.getAttribute('data-field');
          if (name && Object.prototype.hasOwnProperty.call(draft.fields, name)) {
            element.textContent = String(draft.fields[name] || '');
          }
        });
      }
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

  function bumpRevision(main) {
    if (!main.getAttribute || !main.setAttribute) return;
    const current = main.getAttribute('data-resume-revision') || '0';
    const next = (parseInt(current.slice(0, 8), 16) + 1).toString(16).padStart(8, '0');
    main.setAttribute('data-resume-revision', (next + current.slice(8)).padEnd(64, '0').slice(0, 64));
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
    const attrs = { 'data-resume-revision': 'a'.repeat(64) };
    const main = {
      querySelectorAll: (selector) => (selector === 'section' ? [section] : []),
      getAttribute: (name) => attrs[name] || '',
      setAttribute: (name, value) => { attrs[name] = value; },
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
    let releaseExport;
    const worker = {
      set: () => worker,
      from: (source) => { pdfSource = source; return worker; },
      outputPdf: (type) => {
        assert.equal(type, 'arraybuffer');
        return new Promise((resolve) => {
          releaseExport = () => resolve(new TextEncoder().encode('%PDF-1.4 jsPDF\n').buffer);
        });
      },
    };
    let created;
    const editor = install({
      document, storage, pdfFactory: () => worker,
      createObjectURL: (blob) => { created = blob; return 'blob:resume-pdf'; },
      schedule: (callback) => { callback(); return 1; }, cancel: () => {},
    });
    paragraph.innerText = '修改后的内容';
    events.input();
    assert.equal(JSON.parse(values.get(editor.storageKey)).sections[0].content, '修改后的内容');
    const pending = events.click();
    await Promise.resolve();
    releaseExport();
    assert.equal(await pending, true);
    assert.notEqual(pdfSource, main);
    assert.equal(pdfSource.textContent, '修改后的内容');
    assert.equal(download.href, 'blob:resume-pdf');
    assert.equal(download.download, '测试简历.pdf');
    assert.equal(download.hidden, false);
    const exported = new TextDecoder().decode(new Uint8Array(await created.arrayBuffer()));
    assert.match(exported, /FANHAN-RESUME-REVISION [0-9a-f]{64}/);

    const interrupted = events.click();
    await Promise.resolve();
    events.input();
    releaseExport();
    assert.equal(await interrupted, false);
    assert.equal(download.hidden, true);
    assert.equal(download.href, '');
    assert.equal(status.textContent, '导出期间内容已修改，请重新生成 PDF');
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
