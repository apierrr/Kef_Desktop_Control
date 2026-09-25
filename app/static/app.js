/* KEF LSX Web Control — frontend logic */

const $ = (id) => document.getElementById(id);

const sourceButtons = document.querySelectorAll('.source-btn');
const volumeSlider = $('volumeSlider');
const volumeValue = $('volumeValue');
const offBtn = $('offBtn');
const statusEl = $('status');
const statusText = statusEl.querySelector('.status-text');
const toast = $('toast');

let isDraggingVolume = false;
let pendingVolume = null;       // valeur affichée localement, pas encore confirmée
let lastSentVolume = null;
let pollTimer = null;

// ----- Reveal effect : track de la souris sur les boutons -------------------

sourceButtons.forEach((btn) => {
  btn.addEventListener('pointermove', (e) => {
    const r = btn.getBoundingClientRect();
    const x = ((e.clientX - r.left) / r.width) * 100;
    const y = ((e.clientY - r.top) / r.height) * 100;
    btn.style.setProperty('--mx', `${x}%`);
    btn.style.setProperty('--my', `${y}%`);
  });
});

// ----- État / polling -------------------------------------------------------

async function fetchState() {
  try {
    const r = await fetch('/api/state', { cache: 'no-store' });
    const data = await r.json();
    if (data.online) {
      updateUI(data);
      const label = data.is_on ? 'En marche' : 'Veille';
      statusText.textContent = label;
      statusEl.className = 'status online';
    } else {
      setActiveSource(null);
      statusText.textContent = 'Hors ligne';
      statusEl.className = 'status offline';
    }
  } catch (e) {
    setActiveSource(null);
    statusText.textContent = 'Erreur de connexion';
    statusEl.className = 'status offline';
  }
}

function updateUI(state) {
  // Source active — en veille l'enceinte renvoie toujours sa dernière source,
  // mais aucun mode ne doit apparaître sélectionné.
  const activeSource = state.is_on ? state.source : null;
  setActiveSource(activeSource);

  // Volume — uniquement si pas de drag/pending en cours
  if (!isDraggingVolume && pendingVolume === null && state.volume !== null) {
    volumeSlider.value = state.volume;
    volumeValue.textContent = state.volume;
    updateSliderFill();
  }
}

function setActiveSource(source) {
  sourceButtons.forEach((btn) => {
    btn.classList.toggle('active', source !== null && btn.dataset.source === source);
  });
}

function updateSliderFill() {
  const v = volumeSlider.value;
  volumeSlider.style.setProperty('--fill', `${v}%`);
}

// ----- Sources --------------------------------------------------------------

sourceButtons.forEach((btn) => {
  btn.addEventListener('click', async () => {
    const source = btn.dataset.source;
    // Optimistic UI
    setActiveSource(source);

    try {
      const r = await fetch('/api/source', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      // Refresh après court délai pour confirmer
      setTimeout(fetchState, 600);
    } catch (e) {
      showToast('Impossible de changer la source', true);
      fetchState();
    }
  });
});

// ----- Volume slider --------------------------------------------------------

volumeSlider.addEventListener('input', () => {
  const v = parseInt(volumeSlider.value, 10);
  pendingVolume = v;
  volumeValue.textContent = v;
  updateSliderFill();
});

// Pointer events couvrent souris + tactile
volumeSlider.addEventListener('pointerdown', () => {
  isDraggingVolume = true;
});

const finishDrag = async () => {
  if (!isDraggingVolume && pendingVolume === null) return;
  isDraggingVolume = false;
  if (pendingVolume === null) return;
  if (pendingVolume === lastSentVolume) {
    pendingVolume = null;
    return;
  }
  await sendVolume(pendingVolume);
};

volumeSlider.addEventListener('pointerup', finishDrag);
volumeSlider.addEventListener('pointercancel', finishDrag);
// Sécurité : si la souris quitte la fenêtre pendant un drag
window.addEventListener('pointerup', () => {
  if (isDraggingVolume) finishDrag();
});

async function sendVolume(volume) {
  lastSentVolume = volume;
  try {
    const r = await fetch('/api/volume', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ volume }),
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    // On laisse pendingVolume actif un court instant pour éviter le snap-back
    setTimeout(() => { pendingVolume = null; }, 700);
  } catch (e) {
    showToast('Erreur volume', true);
    pendingVolume = null;
    fetchState();
  }
}

// ----- Off ------------------------------------------------------------------

offBtn.addEventListener('click', async () => {
  offBtn.disabled = true;
  setActiveSource(null);  // optimiste : plus aucun mode sélectionné
  try {
    const r = await fetch('/api/off', { method: 'POST' });
    if (!r.ok) throw new Error();
    showToast('Enceinte éteinte');
    setTimeout(fetchState, 800);
  } catch (e) {
    showToast('Erreur lors de l\'extinction', true);
  } finally {
    setTimeout(() => { offBtn.disabled = false; }, 500);
  }
});

// ----- Toast ----------------------------------------------------------------

let toastTimer = null;
function showToast(message, isError = false) {
  if (toastTimer) clearTimeout(toastTimer);
  toast.textContent = message;
  toast.className = 'toast' + (isError ? ' error' : '');
  // Force reflow puis ajoute .show pour que la transition joue
  void toast.offsetWidth;
  toast.classList.add('show');
  toastTimer = setTimeout(() => toast.classList.remove('show'), 2400);
}

// ----- Init -----------------------------------------------------------------

updateSliderFill();
fetchState();
pollTimer = setInterval(fetchState, 5000);

// Reprend le polling actif quand l'onglet redevient visible
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) fetchState();
});
