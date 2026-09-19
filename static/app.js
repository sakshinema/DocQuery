const $ = (selector) => document.querySelector(selector);

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
}

const fileInput = $('#file-input');
const dropzone = $('#dropzone');
const dropTitle = $('#drop-title');
const dropSubtitle = $('#drop-subtitle');
if (fileInput && dropzone) {
  const setFileLabel = () => {
    const file = fileInput.files?.[0];
    dropTitle.textContent = file ? file.name : 'Drop a file here';
    dropSubtitle.textContent = file ? `${Math.ceil(file.size / 1024)} KB · ready to index` : 'or click to browse · PDF, DOCX, TXT, CSV';
  };
  fileInput.addEventListener('change', setFileLabel);
  ['dragenter','dragover'].forEach((event) => dropzone.addEventListener(event, (e) => { e.preventDefault(); dropzone.classList.add('dragover'); }));
  ['dragleave','drop'].forEach((event) => dropzone.addEventListener(event, (e) => { e.preventDefault(); dropzone.classList.remove('dragover'); }));
  dropzone.addEventListener('drop', (e) => { if (e.dataTransfer.files?.length) { fileInput.files = e.dataTransfer.files; setFileLabel(); } });
}

const uploadForm = $('#upload-form');
if (uploadForm) {
  uploadForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const status = $('#upload-status');
    const file = fileInput?.files?.[0];
    if (!file) { status.textContent = 'Choose a file first.'; return; }
    const body = new FormData(); body.append('file', file);
    status.textContent = 'Parsing → chunking → indexing → extracting fields…';
    try {
      const response = await fetch('/api/documents', { method: 'POST', body });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Upload failed');
      status.textContent = data.duplicate ? 'This file is already indexed. Opening the existing record…' : 'Indexed successfully. Opening the structured view…';
      window.location.href = `/documents/${data.id}`;
    } catch (error) {
      status.textContent = error.message || 'Upload failed.';
    }
  });
}

const askForm = $('#ask-form');
if (askForm) {
  askForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const result = $('#ask-result');
    const question = $('#question').value.trim();
    if (!question) { result.textContent = 'Write a question first.'; return; }
    result.textContent = 'Searching for evidence…';
    try {
      const response = await fetch('/api/ask', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({question}) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Question failed');
      const sources = (data.sources || []).map((source, idx) => `
        <a class="source-chip" href="/documents/${source.document_id}">
          <small>[${idx + 1}] ${escapeHtml(source.document_name)}${source.page ? ` · page ${source.page}` : ''}${source.section ? ` · ${escapeHtml(source.section)}` : ''}</small>
          <p>${escapeHtml(source.content.slice(0, 420))}${source.content.length > 420 ? '…' : ''}</p>
        </a>`).join('');
      result.innerHTML = `<div>${escapeHtml(data.answer || '')}</div>${sources ? `<div class="answer-sources">${sources}</div>` : ''}`;
    } catch (error) {
      result.textContent = error.message || 'Question failed.';
    }
  });
}

const librarySearch = $('#library-search');
if (librarySearch) {
  librarySearch.addEventListener('input', () => {
    const query = librarySearch.value.trim().toLowerCase();
    document.querySelectorAll('#doc-list .doc-row').forEach((row) => { row.style.display = !query || row.dataset.search.includes(query) ? '' : 'none'; });
  });
}

document.querySelectorAll('[data-delete-document]').forEach((button) => {
  button.addEventListener('click', async () => {
    if (!confirm('Delete this document and its indexed evidence?')) return;
    const id = button.dataset.deleteDocument;
    const response = await fetch(`/api/documents/${id}`, {method:'DELETE'});
    if (response.ok) window.location.href = '/';
  });
});
