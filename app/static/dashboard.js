let currentApiKey = localStorage.getItem('listenery_api_key') || '';
let selectedDispatchId = null;
let lastDispatches = [];
let knownDispatchIds = new Set();
let firstStreamRender = true;

const apiKeyInput = document.getElementById('apiKeyInput');
apiKeyInput.value = currentApiKey;
updateConnectionStatus();

apiKeyInput.addEventListener('input', (e) => {
  currentApiKey = e.target.value.trim();
  localStorage.setItem('listenery_api_key', currentApiKey);
  updateConnectionStatus();
  fetchDispatches();
});

function updateConnectionStatus() {
  const el = document.getElementById('connectionStatus');
  if (currentApiKey) {
    el.innerHTML = `
      <span class="relative flex h-2 w-2">
        <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-status-sent opacity-75"></span>
        <span class="relative inline-flex rounded-full h-2 w-2 bg-status-sent"></span>
      </span>
      <span>Connected</span>`;
  } else {
    el.innerHTML = `<span class="w-1.5 h-1.5 rounded-full bg-status-sampled"></span><span>Not connected</span>`;
  }
}

function showToast(message, type = 'success') {
  const container = document.getElementById('toastContainer');
  const toast = document.createElement('div');
  toast.className = `px-4 py-3 rounded-lg text-xs font-semibold text-white shadow-xl pointer-events-auto flex items-center gap-2 transition-all transform translate-y-2 opacity-0 ${
    type === 'success' ? 'bg-status-sent' : 'bg-status-risk'
  }`;
  
  const iconSvg = type === 'success' 
    ? `<svg class="w-4 h-4 text-white animate-shield" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>`
    : `<svg class="w-4 h-4 text-white animate-error" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></svg>`;

  toast.innerHTML = `${iconSvg}<span>${escapeHtml(message)}</span>`;
  container.appendChild(toast);

  setTimeout(() => toast.classList.remove('translate-y-2', 'opacity-0'), 50);
  setTimeout(() => {
    toast.classList.add('opacity-0');
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}

async function seedData() {
  const seedBtn = document.getElementById('seedBtn');
  const originalHtml = seedBtn.innerHTML;
  seedBtn.innerHTML = `
    <svg class="w-[18px] h-[18px] animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
      <line x1="12" y1="2" x2="12" y2="6"></line>
      <line x1="12" y1="18" x2="12" y2="22"></line>
      <line x1="4.93" y1="4.93" x2="7.76" y2="7.76"></line>
      <line x1="16.24" y1="16.24" x2="19.07" y2="19.07"></line>
      <line x1="2" y1="12" x2="6" y2="12"></line>
      <line x1="18" y1="12" x2="22" y2="12"></line>
      <line x1="4.93" y1="19.07" x2="7.76" y2="16.24"></line>
      <line x1="16.24" y1="7.76" x2="19.07" y2="4.93"></line>
    </svg>
    Seeding...`;
  seedBtn.disabled = true;

  try {
    const res = await fetch('/admin/seed', { method: 'POST' });
    if (res.ok) {
      const data = await res.json();
      currentApiKey = data.api_key;
      apiKeyInput.value = currentApiKey;
      localStorage.setItem('listenery_api_key', currentApiKey);
      updateConnectionStatus();
      showToast('Workspace seeded — API key active');
      fetchDispatches();
    } else {
      showToast('Failed to seed workspace', 'error');
    }
  } catch (err) {
    console.error('Seed error:', err);
    showToast('Failed to reach server', 'error');
  } finally {
    seedBtn.innerHTML = originalHtml;
    seedBtn.disabled = false;
  }
}

async function triggerQuick(userId, eventName, email) {
  if (!currentApiKey) {
    showToast('Seed the workspace or enter an API key first', 'error');
    return;
  }

  try {
    const res = await fetch('/events', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${currentApiKey}`,
      },
      body: JSON.stringify({
        event_name: eventName,
        user_id: userId,
        email: email,
        properties: { source: 'orchestration_studio' },
        timestamp: new Date().toISOString(),
      }),
    });

    if (res.status === 202) {
      showToast(`Signal emitted for ${userId} (${eventName})`);
      setTimeout(fetchDispatches, 400);
    } else {
      const err = await res.json();
      showToast(`Error: ${err.detail || 'Event rejected'}`, 'error');
    }
  } catch (err) {
    console.error('Trigger error:', err);
    showToast('Network error while dispatching event', 'error');
  }
}

async function submitCustomEvent(e) {
  e.preventDefault();
  const userId = document.getElementById('userIdInput').value.trim();
  const email = document.getElementById('emailInput').value.trim();
  const eventName = document.getElementById('eventNameSelect').value;
  await triggerQuick(userId, eventName, email);
}

async function fetchDispatches() {
  if (!currentApiKey) {
    document.getElementById('streamContainer').innerHTML = `
      <div class="p-8 text-center text-text-muted font-body-sm">
        Seed the workspace or enter an API key to see live dispatches.
      </div>`;
    updateStats([]);
    return;
  }

  try {
    const res = await fetch('/dispatches', {
      headers: { 'Authorization': `Bearer ${currentApiKey}` },
    });

    if (!res.ok) {
      if (res.status === 401) {
        document.getElementById('streamContainer').innerHTML = `
          <div class="p-8 text-center text-status-risk font-body-sm">
            Invalid API key. Click "Seed Workspace" to get a fresh one.
          </div>`;
        updateStats([]);
      }
      return;
    }

    const dispatches = await res.json();
    lastDispatches = dispatches;
    renderStream(dispatches);
    updateStats(dispatches);

    if (selectedDispatchId) {
      const stillThere = dispatches.find((d) => d.id === selectedDispatchId);
      if (stillThere) renderTrail(stillThere);
    }
  } catch (err) {
    console.error('Fetch dispatches error:', err);
  }
}

const STATUS_META = {
  sent: { icon: 'send', color: 'status-sent', label: 'Sent' },
  pending: { icon: 'schedule', color: 'status-pending', label: 'Queued' },
  skipped_duplicate: { icon: 'shield', color: 'status-suppressed', label: 'Suppressed' },
  skipped_sampled_out: { icon: 'tune', color: 'status-sampled', label: 'Sampled Out' },
  failed: { icon: 'error', color: 'status-risk', label: 'Failed' },
};

function headlineFor(d) {
  switch (d.status) {
    case 'sent':
      return `<span class="font-bold">Interview</span> sent to <span class="font-bold">${escapeHtml(d.user_id)}</span>`;
    case 'pending':
      return `Pending send to <span class="font-bold">${escapeHtml(d.user_id)}</span>`;
    case 'skipped_duplicate':
      return `Inbox protection triggered for <span class="font-bold">${escapeHtml(d.user_id)}</span>`;
    case 'skipped_sampled_out':
      return `Not selected for sampling — <span class="font-bold">${escapeHtml(d.user_id)}</span>`;
    case 'failed':
      return `Send failed for <span class="font-bold">${escapeHtml(d.user_id)}</span>`;
    default:
      return escapeHtml(d.user_id);
  }
}

function sublineFor(d) {
  switch (d.status) {
    case 'sent':
      return `Interview: ${d.interview_id} • Sent ${relativeTime(d.sent_at)}`;
    case 'pending':
      return `Interview: ${d.interview_id} • Sends ${countdown(d.due_at)}`;
    case 'skipped_duplicate':
    case 'skipped_sampled_out':
    case 'failed':
      return d.skip_reason || 'No further detail recorded';
    default:
      return d.interview_id;
  }
}

function renderStream(dispatches) {
  const container = document.getElementById('streamContainer');

  if (dispatches.length === 0) {
    container.innerHTML = `
      <div class="p-12 text-center text-text-muted font-body-sm">
        No outreach activity yet. Click a persona card above to simulate an event.
      </div>`;
    return;
  }

  const sorted = [...dispatches].sort((a, b) => new Date(b.created_at) - new Date(a.created_at));

  let newIndex = 0;
  container.innerHTML = sorted
    .map((d) => {
      const meta = STATUS_META[d.status] || { icon: 'help', color: 'text-muted', label: d.status };
      const selected = d.id === selectedDispatchId;
      const isNew = !firstStreamRender && !knownDispatchIds.has(d.id);
      const enterClass = isNew ? 'stream-item-new' : '';
      const enterStyle = isNew ? `style="animation-delay: ${newIndex++ * 60}ms"` : '';
      return `
        <div onclick="selectDispatch('${d.id}')" ${enterStyle} class="${enterClass} bg-white/60 backdrop-blur-[16px] rounded-lg border ${selected ? 'border-primary' : 'border-border-glass'} p-md shadow-sm flex items-center gap-md cursor-pointer hover:shadow-md transition-shadow group">
          <div class="w-10 h-10 rounded-full bg-${meta.color}/12 text-${meta.color} flex items-center justify-center shrink-0">
            ${svgIconFor(d.status, "w-5 h-5")}
          </div>
          <div class="flex-1 min-w-0">
            <p class="font-body-md text-text-primary truncate">${headlineFor(d)}</p>
            <p class="font-body-sm text-text-muted truncate">${escapeHtml(sublineFor(d))}</p>
          </div>
          <div class="font-label-md text-${meta.color} uppercase tracking-wider shrink-0">${meta.label}</div>
        </div>
      `;
    })
    .join('');

  sorted.forEach((d) => knownDispatchIds.add(d.id));
  firstStreamRender = false;
}

function updateStats(dispatches) {
  const counts = { sent: 0, pending: 0, skipped_duplicate: 0, skipped_sampled_out: 0, failed: 0 };
  for (const d of dispatches) {
    if (counts[d.status] !== undefined) counts[d.status] += 1;
  }
  document.querySelector('#chipSent [data-value]').innerText = counts.sent;
  document.querySelector('#chipPending [data-value]').innerText = counts.pending;
  document.querySelector('#chipSuppressed [data-value]').innerText = counts.skipped_duplicate;
  document.querySelector('#chipSampled [data-value]').innerText = counts.skipped_sampled_out;
  document.querySelector('#chipFailed [data-value]').innerText = counts.failed;
}

function trailStep(title, subtitle, state) {
  const dotClass =
    state === 'done' ? 'bg-status-sent' : state === 'failed' ? 'bg-status-risk' : 'bg-status-pending';
  const titleClass = state === 'current' ? 'text-status-pending' : 'text-text-primary';
  return `
    <div class="relative">
      <div class="absolute -left-[30px] top-1 w-3 h-3 rounded-full ${dotClass} border-2 border-white"></div>
      <h4 class="font-body-md font-bold ${titleClass}">${title}</h4>
      <p class="font-body-sm text-text-muted">${subtitle}</p>
    </div>
  `;
}

function messagePreviewFor(d) {
  if (d.status === 'skipped_duplicate') {
    return `[Safeguard active] ${d.user_id} already has an interview in flight for this rule's dedup window — send suppressed to avoid inbox fatigue.`;
  }
  if (d.status === 'skipped_sampled_out') {
    return `[Sampling] ${d.user_id}'s action was recorded but this rule's sample_percent excluded them — no message was composed.`;
  }
  if (d.interview_id.includes('feature')) {
    return `"Hey ${d.user_id}! We saw you tried a new feature — got a minute to tell us how it went?"`;
  }
  return `"Hi ${d.user_id}, we noticed a change on your account. Could you share a minute of feedback with us?"`;
}

function selectDispatch(id) {
  selectedDispatchId = id;
  const d = lastDispatches.find((x) => x.id === id);
  if (d) renderTrail(d);
  renderStream(lastDispatches);
}

function closeTrail() {
  selectedDispatchId = null;
  document.getElementById('trailBody').innerHTML = `
    <p class="text-text-muted font-body-sm">Click any item in the Live Empathy Stream to inspect exactly why it did (or didn't) send.</p>`;
  renderStream(lastDispatches);
}

function renderTrail(d) {
  const sampledOut = d.status === 'skipped_sampled_out';
  const duplicate = d.status === 'skipped_duplicate';

  const steps = [
    trailStep('Event Ingested', `Matched against client rules`, 'done'),
    trailStep('Rule Matched', `Target interview: ${d.interview_id}`, 'done'),
    trailStep(
      'Sample Check',
      sampledOut ? (d.skip_reason || 'Excluded by sample_percent') : 'Passed — included in sample',
      sampledOut ? 'failed' : 'done'
    ),
    trailStep(
      'Dedup Check',
      duplicate ? (d.skip_reason || 'Duplicate within dedup window') : 'Passed — no blocking prior dispatch',
      duplicate ? 'failed' : 'done'
    ),
  ];

  if (!sampledOut && !duplicate) {
    if (d.status === 'sent') {
      steps.push(trailStep('Delivered', `send_interview() ran at ${new Date(d.sent_at).toLocaleTimeString()}`, 'done'));
    } else if (d.status === 'pending') {
      steps.push(trailStep('Awaiting Send Window', `Due ${countdown(d.due_at)}`, 'current'));
    } else if (d.status === 'failed') {
      steps.push(trailStep('Send Failed', d.skip_reason || 'Sender returned failure', 'failed'));
    }
  }

  document.getElementById('trailBody').innerHTML = `
    <div class="mb-lg">
      <span class="font-label-md text-text-muted">Dispatch ID</span>
      <div class="font-data-mono font-bold text-text-primary bg-surface-container-low px-2 py-1 rounded inline-block mt-1 truncate max-w-full">#${d.id.slice(0, 8)}</div>
    </div>
    <div class="relative pl-6 space-y-lg before:content-[''] before:absolute before:left-[11px] before:top-2 before:bottom-2 before:w-[2px] before:bg-surface-container-high">
      ${steps.join('')}
    </div>
    <div class="mt-lg pt-md border-t border-surface-container-low">
      <span class="font-label-md text-text-muted">Message preview</span>
      <p class="font-body-sm text-text-primary italic mt-1">${escapeHtml(messagePreviewFor(d))}</p>
    </div>
  `;
}

function relativeTime(iso) {
  if (!iso) return 'just now';
  const diffMs = Date.now() - new Date(iso).getTime();
  const diffSec = Math.round(diffMs / 1000);
  if (diffSec < 10) return 'just now';
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.round(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.round(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  return `${Math.round(diffHr / 24)}d ago`;
}

function countdown(iso) {
  const diffMs = new Date(iso).getTime() - Date.now();
  if (diffMs <= 0) return 'now (next poll)';
  const diffMin = Math.round(diffMs / 60000);
  if (diffMin < 1) return 'in <1m';
  if (diffMin < 60) return `in ${diffMin}m`;
  const hours = Math.floor(diffMin / 60);
  const mins = diffMin % 60;
  return `in ${hours}h ${mins}m`;
}

function escapeHtml(str) {
  return String(str || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function svgIconFor(status, sizeClass = "w-5 h-5") {
  switch (status) {
    case 'sent':
      return `
        <svg class="${sizeClass} animate-plane" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <line x1="22" y1="2" x2="11" y2="13"></line>
          <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
        </svg>`;
    case 'pending':
      return `
        <svg class="${sizeClass}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="10"></circle>
          <polyline points="12 6 12 12 16 14" class="animate-clock-hand"></polyline>
        </svg>`;
    case 'skipped_duplicate':
      return `
        <svg class="${sizeClass} animate-shield" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path>
          <path d="m9 11 2 2 4-4"></path>
        </svg>`;
    case 'skipped_sampled_out':
      return `
        <svg class="${sizeClass}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <line x1="4" y1="21" x2="4" y2="14"></line>
          <line x1="4" y1="10" x2="4" y2="3"></line>
          <line x1="12" y1="21" x2="12" y2="12"></line>
          <line x1="12" y1="8" x2="12" y2="3"></line>
          <line x1="20" y1="21" x2="20" y2="16"></line>
          <line x1="20" y1="12" x2="20" y2="3"></line>
          <line x1="2" y1="14" x2="6" y2="14" class="animate-slider-1"></line>
          <line x1="10" y1="8" x2="14" y2="8" class="animate-slider-2"></line>
          <line x1="18" y1="16" x2="22" y2="16" class="animate-slider-1"></line>
        </svg>`;
    case 'failed':
    default:
      return `
        <svg class="${sizeClass} animate-error" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="10"></circle>
          <line x1="12" y1="8" x2="12" y2="12"></line>
          <line x1="12" y1="16" x2="12.01" y2="16"></line>
        </svg>`;
  }
}

fetchDispatches();
setInterval(fetchDispatches, 2000);
