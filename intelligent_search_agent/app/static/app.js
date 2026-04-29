const TABLE_MODES = new Set(['asset_table', 'mixed']);

const state = {
  sessionId: localStorage.getItem('isaSessionId') || crypto.randomUUID(),
  assets: [],
  documents: [],
  selectedRef: null,
  selectedImageIndex: 0,
  mode: 'chat',
  route: null,
  history: [],
  pendingFindings: null,
  busy: false,
};

const els = {
  workspace: document.querySelector('#workspace'),
  form: document.querySelector('#chatForm'),
  input: document.querySelector('#questionInput'),
  send: document.querySelector('#sendButton'),
  messages: document.querySelector('#messages'),
  status: document.querySelector('#statusText'),
  newChat: document.querySelector('#newChatButton'),
  examples: Array.from(document.querySelectorAll('[data-prompt]')),
  findingsTitle: document.querySelector('#findingsTitle'),
  findingsBody: document.querySelector('#findingsBody'),
  findingCount: document.querySelector('#findingCount'),
  findingsMeta: document.querySelector('#findingsMeta'),
  findingDetail: document.querySelector('#findingDetail'),
  imageModal: document.querySelector('#imageModal'),
  modalImage: document.querySelector('#modalImage'),
  modalTitle: document.querySelector('#modalTitle'),
  modalDescription: document.querySelector('#modalDescription'),
  modalMeta: document.querySelector('#modalMeta'),
  modalOpenLink: document.querySelector('#modalOpenLink'),
  modalSourceLink: document.querySelector('#modalSourceLink'),
  modalPrev: document.querySelector('#modalPrev'),
  modalNext: document.querySelector('#modalNext'),
  documentModal: document.querySelector('#documentModal'),
  documentFrame: document.querySelector('#documentFrame'),
  documentModalTitle: document.querySelector('#documentModalTitle'),
  documentModalMeta: document.querySelector('#documentModalMeta'),
  documentExcerpt: document.querySelector('#documentExcerpt'),
  documentOpenLink: document.querySelector('#documentOpenLink'),
  documentSourceLink: document.querySelector('#documentSourceLink'),
};

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function scoreLabel(score) {
  if (score === null || score === undefined) return '';
  return `${Math.round(Number(score) * 100)}%`;
}

function truncate(value, max = 220) {
  const text = String(value ?? '').replace(/\s+/g, ' ').trim();
  if (text.length <= max) return text;
  return `${text.slice(0, max - 1)}...`;
}

function appendMessage(role, text = '') {
  const article = document.createElement('article');
  article.className = `message ${role}`;
  article.innerHTML = `
    <div class="avatar">${role === 'user' ? 'You' : 'AI'}</div>
    <div class="message-content">
      <div class="bubble ${role === 'assistant' ? 'is-streaming' : ''}">${escapeHtml(text)}</div>
      <div class="source-citations" hidden></div>
    </div>
  `;
  els.messages.appendChild(article);
  els.messages.scrollTop = els.messages.scrollHeight;
  return {
    article,
    bubble: article.querySelector('.bubble'),
    citations: article.querySelector('.source-citations'),
  };
}

function initialAssistantHtml() {
  return `
    <article class="message assistant">
      <div class="avatar">AI</div>
      <div class="message-content">
        <div class="bubble">What should we look up in the Belgian corpus?</div>
        <div class="source-citations" hidden></div>
      </div>
    </article>
  `;
}

function setBubbleText(bubble, text) {
  bubble.textContent = text;
  els.messages.scrollTop = els.messages.scrollHeight;
}

function findingType(item) {
  return item.asset_kind || 'asset';
}

function documentLabel(item) {
  const title = item.title || 'Document';
  const page = item.page_number ? `p. ${item.page_number}` : 'page unknown';
  return `${title} (${page})`;
}

function setDisplayMode(mode) {
  state.mode = mode;
  const showTable = TABLE_MODES.has(mode);
  els.workspace.classList.toggle('chat-only', !showTable);
  els.findingsTitle.textContent = mode === 'mixed' ? 'Image Findings' : 'Findings';
}

function clearFindings(message = 'No image findings for this answer.') {
  state.assets = [];
  state.selectedRef = null;
  state.selectedImageIndex = 0;
  els.findingCount.textContent = '0';
  els.findingsMeta.textContent = 'Chat response';
  els.findingsBody.innerHTML = `<tr><td colspan="7" class="empty-cell">${escapeHtml(message)}</td></tr>`;
  renderFindingDetail(null);
}

function renderCitations(container, documents) {
  if (!container || !documents.length) {
    if (container) {
      container.hidden = true;
      container.innerHTML = '';
    }
    return;
  }

  container.hidden = false;
  container.innerHTML = `
    <span>Sources</span>
    ${documents
      .slice(0, 6)
      .map((item) => {
        return `<button type="button" class="source-chip" data-doc-ref="${escapeHtml(
          item.ref,
        )}">${escapeHtml(item.ref)}: ${escapeHtml(documentLabel(item))}</button>`;
      })
      .join('')}
  `;
  for (const button of container.querySelectorAll('[data-doc-ref]')) {
    button.addEventListener('click', () => openDocumentModalByRef(button.dataset.docRef));
  }
  els.messages.scrollTop = els.messages.scrollHeight;
}

function renderFindings(findings, question, mode = 'asset_table') {
  setDisplayMode(mode);
  state.assets = findings.assets || [];
  state.documents = findings.documents || [];

  if (!TABLE_MODES.has(mode)) {
    clearFindings('This request does not involve image assets, so the response stays in chat.');
    return;
  }

  state.selectedRef = state.assets[0]?.ref ?? null;
  state.selectedImageIndex = 0;
  els.findingCount.textContent = String(state.assets.length);
  els.findingsMeta.textContent = mode === 'mixed' ? `${question} - images` : question;

  if (!state.assets.length) {
    els.findingsBody.innerHTML = '<tr><td colspan="7" class="empty-cell">No image findings found.</td></tr>';
    renderFindingDetail(null);
    return;
  }

  els.findingsBody.innerHTML = state.assets
    .map((item) => {
      const preview = item.preview_url
        ? `<img src="${escapeHtml(item.preview_url)}" alt="" loading="lazy" />`
        : '<span>IMG</span>';
      return `
        <tr data-ref="${escapeHtml(item.ref)}" class="${item.ref === state.selectedRef ? 'is-selected' : ''}">
          <td><div class="preview">${preview}</div></td>
          <td><strong>${escapeHtml(item.ref)}</strong></td>
          <td class="title-cell" title="${escapeHtml(item.title)}">${escapeHtml(item.title || 'Untitled')}</td>
          <td>${escapeHtml(findingType(item))}</td>
          <td>${escapeHtml(item.period || '')}</td>
          <td>${escapeHtml(scoreLabel(item.score))}</td>
          <td><button class="show-button" type="button" data-show-ref="${escapeHtml(item.ref)}">Show</button></td>
        </tr>
      `;
    })
    .join('');

  for (const row of els.findingsBody.querySelectorAll('tr[data-ref]')) {
    row.addEventListener('click', (event) => {
      if (event.target.closest('button')) return;
      selectFinding(row.dataset.ref);
    });
  }
  for (const button of els.findingsBody.querySelectorAll('[data-show-ref]')) {
    button.addEventListener('click', () => openImageModalByRef(button.dataset.showRef));
  }
  renderFindingDetail(state.assets[0]);
}

function selectFinding(ref) {
  state.selectedRef = ref;
  state.selectedImageIndex = Math.max(
    0,
    state.assets.findIndex((item) => item.ref === ref),
  );
  for (const row of els.findingsBody.querySelectorAll('tr[data-ref]')) {
    row.classList.toggle('is-selected', row.dataset.ref === ref);
  }
  renderFindingDetail(state.assets.find((item) => item.ref === ref));
}

function renderFindingDetail(item) {
  if (!item) {
    els.findingDetail.innerHTML = `
      <h3>Selected Finding</h3>
      <p>No image is selected.</p>
    `;
    return;
  }

  const tags = item.metadata?.tags || item.metadata?.vlm_entry?.search_keywords || [];
  const badges = [
    item.ref,
    findingType(item),
    item.period,
    item.language,
    scoreLabel(item.score),
  ]
    .filter(Boolean)
    .map((value) => `<span class="badge">${escapeHtml(value)}</span>`)
    .join('');

  els.findingDetail.innerHTML = `
    ${item.preview_url ? `<img class="detail-image" src="${escapeHtml(item.preview_url)}" alt="" />` : ''}
    <h3>${escapeHtml(item.title || 'Untitled')}</h3>
    <p>${escapeHtml(truncate(item.summary, 800))}</p>
    <div class="metadata-line">${badges}</div>
    ${
      Array.isArray(tags) && tags.length
        ? `<p><strong>Tags:</strong> ${escapeHtml(tags.slice(0, 14).join(', '))}</p>`
        : ''
    }
    <div class="detail-actions">
      <button class="show-button" type="button" data-detail-show="${escapeHtml(item.ref)}">Show</button>
      ${
        item.preview_url
          ? `<a href="${escapeHtml(item.preview_url)}" target="_blank" rel="noreferrer">Open image</a>`
          : ''
      }
      ${
        item.source_url
          ? `<a href="${escapeHtml(item.source_url)}" target="_blank" rel="noreferrer">Source</a>`
          : ''
      }
    </div>
  `;

  const showButton = els.findingDetail.querySelector('[data-detail-show]');
  if (showButton) {
    showButton.addEventListener('click', () => openImageModalByRef(showButton.dataset.detailShow));
  }
}

function openImageModalByRef(ref) {
  selectFinding(ref);
  openImageModal(state.selectedImageIndex);
}

function openImageModal(index) {
  if (!state.assets.length) return;
  state.selectedImageIndex = Math.min(Math.max(index, 0), state.assets.length - 1);
  const item = state.assets[state.selectedImageIndex];
  state.selectedRef = item.ref;
  updateModalContent(item);
  if (typeof els.imageModal.showModal === 'function') {
    if (!els.imageModal.open) els.imageModal.showModal();
  } else {
    els.imageModal.classList.add('is-open');
  }
}

function updateModalContent(item) {
  els.modalImage.src = item.preview_url || '';
  els.modalImage.alt = item.title || '';
  els.modalTitle.textContent = `${item.ref}: ${item.title || 'Untitled'}`;
  els.modalDescription.textContent = truncate(item.summary, 900);
  els.modalMeta.innerHTML = [
    findingType(item),
    item.period,
    item.language,
    scoreLabel(item.score),
  ]
    .filter(Boolean)
    .map((value) => `<span class="badge">${escapeHtml(value)}</span>`)
    .join('');
  els.modalOpenLink.href = item.preview_url || '#';
  els.modalOpenLink.toggleAttribute('hidden', !item.preview_url);
  els.modalSourceLink.href = item.source_url || '#';
  els.modalSourceLink.toggleAttribute('hidden', !item.source_url);
  els.modalPrev.disabled = state.selectedImageIndex === 0;
  els.modalNext.disabled = state.selectedImageIndex >= state.assets.length - 1;
}

function closeModal() {
  if (els.imageModal.open) {
    els.imageModal.close();
  } else {
    els.imageModal.classList.remove('is-open');
  }
}

function openDocumentModalByRef(ref) {
  const item = state.documents.find((document) => document.ref === ref);
  if (!item) return;
  openDocumentModal(item);
}

function openDocumentModal(item) {
  const openUrl = item.open_url || item.source_url || item.detail_url || '#';
  els.documentModalTitle.textContent = `${item.ref}: ${item.title || 'Document'}`;
  els.documentModalMeta.innerHTML = [
    item.doc_type || 'pdf',
    item.page_number ? `p. ${item.page_number}` : '',
    item.language,
    scoreLabel(item.score),
  ]
    .filter(Boolean)
    .map((value) => `<span class="badge">${escapeHtml(value)}</span>`)
    .join('');
  els.documentExcerpt.textContent = truncate(item.summary, 1600);
  els.documentFrame.src = openUrl;
  els.documentOpenLink.href = openUrl;
  els.documentSourceLink.href = item.source_url || openUrl;
  els.documentSourceLink.toggleAttribute('hidden', !item.source_url);

  if (typeof els.documentModal.showModal === 'function') {
    if (!els.documentModal.open) els.documentModal.showModal();
  } else {
    els.documentModal.classList.add('is-open');
  }
}

function closeDocumentModal() {
  els.documentFrame.src = 'about:blank';
  if (els.documentModal.open) {
    els.documentModal.close();
  } else {
    els.documentModal.classList.remove('is-open');
  }
}

function parseSseEvents(buffer) {
  const events = [];
  let cursor = buffer.indexOf('\n\n');
  while (cursor !== -1) {
    const raw = buffer.slice(0, cursor);
    buffer = buffer.slice(cursor + 2);
    const dataLines = raw
      .split('\n')
      .filter((line) => line.startsWith('data: '))
      .map((line) => line.slice(6));
    if (dataLines.length) {
      events.push(JSON.parse(dataLines.join('\n')));
    }
    cursor = buffer.indexOf('\n\n');
  }
  return { events, buffer };
}

async function ask(question) {
  if (state.busy) return;
  state.busy = true;
  state.route = null;
  state.documents = [];
  state.pendingFindings = null;
  els.send.disabled = true;
  els.send.textContent = 'Working';
  els.status.textContent = 'Planning request';
  setDisplayMode('chat');
  clearFindings('Searching...');

  appendMessage('user', question);
  const assistantMessage = appendMessage('assistant', '');
  let answer = '';
  let buffer = '';

  try {
    const response = await fetch('/v1/chat/companion/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question,
        session_id: state.sessionId,
        messages: state.history.slice(-8),
      }),
    });
    if (!response.ok || !response.body) {
      throw new Error(`Assistant request failed: ${response.status}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parsed = parseSseEvents(buffer);
      buffer = parsed.buffer;
      for (const event of parsed.events) {
        if (event.type === 'status') {
          els.status.textContent = event.message;
        } else if (event.type === 'session') {
          state.sessionId = event.session_id;
          localStorage.setItem('isaSessionId', state.sessionId);
        } else if (event.type === 'route') {
          state.route = event.route;
          els.status.textContent = event.memory?.used
            ? `Route: ${event.route.intent.replace('_', ' ')} with memory`
            : `Route: ${event.route.intent.replace('_', ' ')}`;
        } else if (event.type === 'findings') {
          state.pendingFindings = event.findings;
          renderFindings(event.findings, question, event.mode);
          renderCitations(assistantMessage.citations, state.documents);
          els.status.textContent = TABLE_MODES.has(event.mode) ? 'Findings ready' : 'Writing answer';
        } else if (event.type === 'chunk') {
          answer += event.content || '';
          setBubbleText(assistantMessage.bubble, answer);
        } else if (event.type === 'done') {
          renderCitations(assistantMessage.citations, state.documents);
          if (event.mode === 'asset_table') {
            els.status.textContent = `Done: ${event.counts.assets} image findings`;
          } else if (event.mode === 'mixed') {
            els.status.textContent = `Done: ${event.counts.assets} images, ${event.counts.documents} sources`;
          } else {
            els.status.textContent = 'Done';
          }
        } else if (event.type === 'error') {
          throw new Error(event.message);
        }
      }
    }
    if (!answer.trim()) {
      setBubbleText(assistantMessage.bubble, 'No answer was returned.');
    }
    state.history.push({ role: 'user', content: question });
    state.history.push({ role: 'assistant', content: answer.trim() || assistantMessage.bubble.textContent || '' });
    state.history = state.history.slice(-10);
  } catch (error) {
    assistantMessage.bubble.classList.add('error');
    setBubbleText(assistantMessage.bubble, `Something went wrong: ${error.message}`);
    els.status.textContent = 'Error';
  } finally {
    assistantMessage.bubble.classList.remove('is-streaming');
    state.busy = false;
    els.send.disabled = false;
    els.send.textContent = 'Ask';
    els.input.focus();
  }
}

els.form.addEventListener('submit', (event) => {
  event.preventDefault();
  const question = els.input.value.trim();
  if (!question) return;
  ask(question);
});

els.input.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
    els.form.requestSubmit();
  }
});

for (const item of els.examples) {
  item.addEventListener('click', () => {
    els.input.value = item.dataset.prompt;
    els.form.requestSubmit();
  });
}

els.newChat.addEventListener('click', () => {
  state.sessionId = crypto.randomUUID();
  localStorage.setItem('isaSessionId', state.sessionId);
  state.history = [];
  state.documents = [];
  state.assets = [];
  els.messages.innerHTML = initialAssistantHtml();
  setDisplayMode('chat');
  clearFindings('New chat started.');
  els.status.textContent = 'New chat';
  els.input.focus();
});

for (const button of document.querySelectorAll('[data-modal-close]')) {
  button.addEventListener('click', closeModal);
}

for (const button of document.querySelectorAll('[data-document-close]')) {
  button.addEventListener('click', closeDocumentModal);
}

els.modalPrev.addEventListener('click', () => openImageModal(state.selectedImageIndex - 1));
els.modalNext.addEventListener('click', () => openImageModal(state.selectedImageIndex + 1));
els.imageModal.addEventListener('click', (event) => {
  if (event.target === els.imageModal) closeModal();
});
els.documentModal.addEventListener('click', (event) => {
  if (event.target === els.documentModal) closeDocumentModal();
});
