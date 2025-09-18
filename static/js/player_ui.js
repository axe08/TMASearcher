(function (window, document) {
  'use strict';

  const STORAGE_SESSION_KEY = 'lastPlayerSession';
  const PROGRESS_PREFIX = 'progress-';

  const queueElements = {
    panel: null,
    header: null,
    count: null,
    list: null,
    empty: null,
    collapseBtn: null,
    clearBtn: null,
  };

  const config = {
    onQueueAdvance: null,
  };

  let defaultDocumentTitle = document.title;
  let audioPlayer = null;
  let currentEpisode = null;
  let queueCollapsed = true;
  let queueListenersBound = false;
  let audioBarRefreshRaf = null;
  let initialised = false;

  function cloneEpisode(episode) {
    return episode ? { ...episode } : null;
  }

  function showToast(message, isRemove) {
    const existingToast = document.querySelector('.toast-notification');
    if (existingToast) {
      existingToast.remove();
    }

    const toast = document.createElement('div');
    toast.className = `toast-notification ${isRemove ? 'remove' : ''}`;
    toast.innerHTML = `<i class="fas fa-${isRemove ? 'trash' : 'check'}"></i><span>${message}</span>`;

    document.body.appendChild(toast);

    requestAnimationFrame(() => {
      toast.classList.add('show');
    });

    setTimeout(() => {
      toast.classList.remove('show');
      setTimeout(() => toast.remove(), 300);
    }, 2500);
  }

  function decodeInlineString(value) {
    if (!value) {
      return '';
    }
    return value
      .replace(/\\'/g, "'")
      .replace(/\\\"/g, '\"');
  }

  function buildEpisodePayload(id, title, date, showNotes, mp3url, url) {
    return {
      id: Number(id) || id,
      title: decodeInlineString(title) || 'Untitled Episode',
      date: date || '',
      show_notes: decodeInlineString(showNotes || ''),
      mp3url: decodeInlineString(mp3url || ''),
      url: decodeInlineString(url || ''),
    };
  }

  function ensureAudioPlayer() {
    if (!audioPlayer) {
      audioPlayer = document.getElementById('audioPlayer');
    }
    return audioPlayer;
  }

  function scheduleAudioBarRefresh() {
    if (audioBarRefreshRaf) {
      cancelAnimationFrame(audioBarRefreshRaf);
    }

    audioBarRefreshRaf = requestAnimationFrame(() => {
      const controlBar = document.getElementById('audioControlBar');
      let offset = 0;
      if (controlBar) {
        const styles = window.getComputedStyle(controlBar);
        if (styles.display !== 'none' && styles.visibility !== 'hidden') {
          offset = Math.ceil(controlBar.getBoundingClientRect().height);
        }
      }
      document.body.style.setProperty('--audio-bar-offset', `${offset}px`);
      audioBarRefreshRaf = null;
    });
  }

  function hydrateQueueElements() {
    if (queueElements.panel && queueElements.list) {
      return true;
    }

    queueElements.panel = document.getElementById('playQueuePanel');
    if (!queueElements.panel) {
      return false;
    }

    queueElements.header = document.getElementById('playQueueHeader');
    queueElements.count = document.getElementById('queueCount');
    queueElements.list = document.getElementById('playQueueList');
    queueElements.empty = document.getElementById('queueEmptyState');
    queueElements.collapseBtn = document.getElementById('queueCollapseBtn');
    queueElements.clearBtn = document.getElementById('queueClearBtn');
    return true;
  }

  function getQueueState() {
    if (typeof PlayQueue === 'undefined') {
      return { current: null, queue: [] };
    }
    return PlayQueue.getState();
  }

  function setQueueCollapsed(collapsed) {
    queueCollapsed = Boolean(collapsed);
    if (!queueElements.panel) {
      return;
    }

    queueElements.panel.classList.toggle('collapsed', queueCollapsed);
    if (queueElements.collapseBtn) {
      queueElements.collapseBtn.textContent = queueCollapsed ? 'Show' : 'Hide';
    }
    scheduleAudioBarRefresh();
  }

  function toggleQueuePanel(forceState) {
    if (!hydrateQueueElements()) {
      return;
    }

    if (typeof forceState === 'boolean') {
      setQueueCollapsed(forceState);
      return;
    }

    setQueueCollapsed(!queueCollapsed);
  }

  function renderQueuePanel(state) {
    if (!hydrateQueueElements()) {
      return;
    }

    const queueState = state || getQueueState();
    const { current, queue } = queueState;
    const hasItems = Boolean(current) || (Array.isArray(queue) && queue.length > 0);

    queueElements.panel.style.display = hasItems ? 'block' : 'none';
    if (!hasItems) {
      setQueueCollapsed(true);
      if (queueElements.count) {
        queueElements.count.textContent = '(0)';
      }
      if (queueElements.empty) {
        queueElements.empty.style.display = 'block';
      }
      if (queueElements.list) {
        queueElements.list.innerHTML = '';
      }
      scheduleAudioBarRefresh();
      return;
    }

    const totalItems = (current ? 1 : 0) + (queue ? queue.length : 0);
    if (queueElements.count) {
      queueElements.count.textContent = `(${totalItems})`;
    }

    if (!queueElements.list) {
      return;
    }

    const entries = [];
    if (current) {
      entries.push({ ...current, isCurrent: true });
    }
    if (Array.isArray(queue)) {
      queue.forEach((episode) => entries.push({ ...episode, isCurrent: false }));
    }

    queueElements.list.innerHTML = '';

    if (!entries.length) {
      if (queueElements.empty) {
        queueElements.empty.style.display = 'block';
      }
      scheduleAudioBarRefresh();
      return;
    }

    if (queueElements.empty) {
      queueElements.empty.style.display = 'none';
    }

    const fragment = document.createDocumentFragment();

    entries.forEach((episode) => {
      const itemEl = document.createElement('div');
      itemEl.className = 'play-queue-item' + (episode.isCurrent ? ' active' : '');

      const infoEl = document.createElement('div');
      infoEl.className = 'play-queue-info';

      const titleEl = document.createElement('div');
      titleEl.className = 'play-queue-title';
      titleEl.textContent = episode.title;

      const dateEl = document.createElement('div');
      dateEl.className = 'play-queue-date';
      dateEl.textContent = episode.isCurrent ? `${episode.date} • Now playing` : episode.date;

      infoEl.appendChild(titleEl);
      infoEl.appendChild(dateEl);
      itemEl.appendChild(infoEl);

      const actionsEl = document.createElement('div');
      actionsEl.className = 'play-queue-actions';

      if (!episode.isCurrent && episode.mp3url) {
        const playBtn = document.createElement('button');
        playBtn.type = 'button';
        playBtn.textContent = 'Play';
        playBtn.addEventListener('click', (event) => {
          event.stopPropagation();
          if (typeof PlayQueue !== 'undefined') {
            PlayQueue.setCurrent(episode);
          }
          startPlayback(episode, { openModal: false });
          setQueueCollapsed(false);
        });
        actionsEl.appendChild(playBtn);
      }

      const removeBtn = document.createElement('button');
      removeBtn.type = 'button';
      removeBtn.textContent = 'Remove';
      removeBtn.addEventListener('click', (event) => {
        event.stopPropagation();
        if (typeof PlayQueue !== 'undefined') {
          PlayQueue.remove(episode.id);
        }
        showToast('Removed from queue', true);
      });
      actionsEl.appendChild(removeBtn);

      itemEl.appendChild(actionsEl);

      if (episode.mp3url) {
        itemEl.addEventListener('dblclick', () => {
          if (typeof PlayQueue !== 'undefined') {
            PlayQueue.setCurrent(episode);
          }
          startPlayback(episode, { openModal: false });
          setQueueCollapsed(false);
        });
      }

      fragment.appendChild(itemEl);
    });

    queueElements.list.appendChild(fragment);
    scheduleAudioBarRefresh();
  }

  function bindQueuePanelEvents() {
    if (queueListenersBound || !hydrateQueueElements()) {
      return;
    }

    if (queueElements.header) {
      queueElements.header.addEventListener('click', () => {
        toggleQueuePanel();
      });
    }

    if (queueElements.collapseBtn) {
      queueElements.collapseBtn.addEventListener('click', (event) => {
        event.stopPropagation();
        toggleQueuePanel();
      });
    }

    if (queueElements.clearBtn) {
      queueElements.clearBtn.addEventListener('click', (event) => {
        event.stopPropagation();
        if (typeof PlayQueue !== 'undefined') {
          PlayQueue.clear();
        }
        showToast('Queue cleared', true);
      });
    }

    queueListenersBound = true;
  }

  function savePlayerSession(episodeId, title, mp3url, date, currentTime, isPlaying, url) {
    const session = {
      episodeId,
      title: title || 'Untitled Episode',
      mp3url: mp3url || '',
      date: date || '',
      url: url || '',
      currentTime: currentTime || 0,
      isPlaying: Boolean(isPlaying),
      timestamp: Date.now(),
    };
    try {
      localStorage.setItem(STORAGE_SESSION_KEY, JSON.stringify(session));
    } catch (err) {
      console.warn('Unable to persist player session', err);
    }
  }

  function loadPlayerSession() {
    const raw = localStorage.getItem(STORAGE_SESSION_KEY);
    if (!raw) {
      return null;
    }
    try {
      return JSON.parse(raw);
    } catch (err) {
      console.warn('Unable to parse player session', err);
      return null;
    }
  }

  function clearPlayerSession() {
    localStorage.removeItem(STORAGE_SESSION_KEY);
  }

  function getCurrentPlaybackMetadata() {
    if (currentEpisode && currentEpisode.id) {
      return cloneEpisode(currentEpisode);
    }

    if (typeof PlayQueue !== 'undefined') {
      const state = PlayQueue.getState();
      if (state.current && state.current.id) {
        return cloneEpisode(state.current);
      }
    }

    const session = loadPlayerSession();
    if (session && session.episodeId) {
      return {
        id: session.episodeId,
        title: session.title || 'Untitled Episode',
        date: session.date || '',
        mp3url: session.mp3url || '',
        url: session.url || '',
      };
    }

    return null;
  }

  function updatePlaybackLabels(metadata) {
    const trackTitleEl = document.getElementById('currentTrackTitle');
    const modalLabel = document.getElementById('audioPlayerModalLabel');

    if (!metadata || !metadata.id) {
      if (trackTitleEl) {
        trackTitleEl.textContent = 'Nothing playing';
      }
      if (modalLabel) {
        modalLabel.textContent = 'Now Playing';
      }
      document.title = defaultDocumentTitle;
      return;
    }

    const displayTitle = metadata.title || 'Untitled Episode';
    const dateSuffix = metadata.date ? ` (${metadata.date})` : '';

    if (trackTitleEl) {
      trackTitleEl.textContent = `${displayTitle}${dateSuffix}`;
    }
    if (modalLabel) {
      modalLabel.textContent = `${displayTitle}${dateSuffix}`;
    }
    document.title = `${displayTitle} | TMA Searcher`;
  }

  function applyButtonState(isPlaying) {
    const controlPlayBtn = document.getElementById('controlPlayPauseBtn');
    const modalPlayBtn = document.getElementById('modalPlayPauseBtn');
    const label = isPlaying ? 'Pause' : 'Play';
    if (controlPlayBtn) {
      controlPlayBtn.textContent = label;
    }
    if (modalPlayBtn) {
      modalPlayBtn.textContent = label;
    }
  }

  function setCurrentEpisode(episode) {
    currentEpisode = episode ? { ...episode } : null;
  }

  function persistProgress() {
    const player = ensureAudioPlayer();
    if (!player || !currentEpisode || !currentEpisode.id) {
      return;
    }

    try {
      if (!player.paused && !player.ended) {
        localStorage.setItem(`${PROGRESS_PREFIX}${currentEpisode.id}`, player.currentTime);
      }
    } catch (err) {
      console.warn('Unable to persist progress', err);
    }

    savePlayerSession(
      currentEpisode.id,
      currentEpisode.title,
      currentEpisode.mp3url,
      currentEpisode.date,
      player.currentTime || 0,
      !player.paused,
      currentEpisode.url || ''
    );
  }

  function startPlayback(episode, options) {
    const playbackOptions = { openModal: true, resumeProgress: true, ...options };
    if (!episode || !episode.mp3url) {
      alert('Stream not available for this episode.');
      return;
    }

    const player = ensureAudioPlayer();
    if (!player) {
      console.warn('Audio element is not available');
      return;
    }

    setCurrentEpisode(episode);

    const audioSourceEl = document.getElementById('audioSource');
    if (audioSourceEl) {
      audioSourceEl.setAttribute('src', episode.mp3url || '');
    }
    player.load();

    if (playbackOptions.resumeProgress) {
      const saved = localStorage.getItem(`${PROGRESS_PREFIX}${episode.id}`);
      if (saved) {
        player.currentTime = parseFloat(saved);
      }
    }

    const playPromise = player.play();
    if (playPromise && typeof playPromise.catch === 'function') {
      playPromise.catch(() => {});
    }

    const controlBar = document.getElementById('audioControlBar');
    if (controlBar) {
      controlBar.style.display = 'flex';
    }

    document.body.classList.add('audio-playing');
    applyButtonState(true);
    scheduleAudioBarRefresh();

    if (typeof PlayQueue !== 'undefined') {
      PlayQueue.setCurrent(episode, { enqueueIfMissing: false });
      renderQueuePanel(getQueueState());
    }

    savePlayerSession(
      episode.id,
      episode.title,
      episode.mp3url,
      episode.date,
      player.currentTime || 0,
      true,
      episode.url || ''
    );

    updatePlaybackLabels(episode);

    if (playbackOptions.openModal && typeof $ !== 'undefined' && window.$) {
      const modal = window.$('#audioPlayerModal');
      if (modal && modal.length) {
        modal.modal('show');
      }
    }
  }

  function toggleAudioPlayPause() {
    const player = ensureAudioPlayer();
    if (!player) {
      return;
    }

    if (player.paused) {
      const playPromise = player.play();
      if (playPromise && typeof playPromise.catch === 'function') {
        playPromise.catch(() => {});
      }
      applyButtonState(true);
    } else {
      player.pause();
      applyButtonState(false);
    }

    persistProgress();
    updatePlaybackLabels(getCurrentPlaybackMetadata());
  }

  function seekAudio(deltaSeconds) {
    const player = ensureAudioPlayer();
    if (!player) {
      return;
    }

    const newTime = Math.min(Math.max(player.currentTime + deltaSeconds, 0), player.duration || Number.MAX_VALUE);
    player.currentTime = newTime;
    persistProgress();
  }

  function reopenPlayer() {
    if (typeof $ === 'undefined' || !window.$) {
      return;
    }
    const modal = window.$('#audioPlayerModal');
    if (modal && modal.length) {
      updatePlaybackLabels(getCurrentPlaybackMetadata());
      modal.modal('show');
    }
  }

  function handleQueueAdvance(nextEpisode) {
    if (typeof config.onQueueAdvance === 'function') {
      const handled = config.onQueueAdvance(nextEpisode);
      if (handled === true) {
        return;
      }
    }

    if (nextEpisode && nextEpisode.mp3url) {
      startPlayback(nextEpisode, { openModal: false });
      return;
    }

    const player = ensureAudioPlayer();
    if (player) {
      player.pause();
    }
    setCurrentEpisode(null);
    clearPlayerSession();

    const controlBar = document.getElementById('audioControlBar');
    if (controlBar) {
      controlBar.style.display = 'none';
    }
    document.body.classList.remove('audio-playing');
    scheduleAudioBarRefresh();

    updatePlaybackLabels(getCurrentPlaybackMetadata());
    renderQueuePanel(getQueueState());
  }

  function handleQueueUpdated(event) {
    renderQueuePanel(event.detail);
    updatePlaybackLabels(getCurrentPlaybackMetadata());
  }

  function handleAudioPlay() {
    applyButtonState(true);
    document.body.classList.add('audio-playing');
    scheduleAudioBarRefresh();
    updatePlaybackLabels(getCurrentPlaybackMetadata());
  }

  function handleAudioPause() {
    applyButtonState(false);
    persistProgress();
    updatePlaybackLabels(getCurrentPlaybackMetadata());
  }

  function handleAudioEnded() {
    const player = ensureAudioPlayer();
    if (player && currentEpisode && currentEpisode.id) {
      try {
        localStorage.removeItem(`${PROGRESS_PREFIX}${currentEpisode.id}`);
      } catch (err) {
        console.warn('Unable to clear progress', err);
      }
    }

    clearPlayerSession();

    let nextEpisode = null;
    if (typeof PlayQueue !== 'undefined') {
      nextEpisode = PlayQueue.next();
    }

    handleQueueAdvance(nextEpisode);
  }

  function attachAudioListeners() {
    const player = ensureAudioPlayer();
    if (!player) {
      return;
    }

    player.addEventListener('timeupdate', persistProgress);
    player.addEventListener('play', handleAudioPlay);
    player.addEventListener('pause', handleAudioPause);
    player.addEventListener('ended', handleAudioEnded);
  }

  function initialiseFromSession() {
    const session = loadPlayerSession();
    if (!session || !session.episodeId) {
      updatePlaybackLabels(getCurrentPlaybackMetadata());
      return;
    }

    const player = ensureAudioPlayer();
    if (!player) {
      return;
    }

    const restored = {
      id: session.episodeId,
      title: session.title || 'Untitled Episode',
      date: session.date || '',
      mp3url: session.mp3url || '',
      url: session.url || '',
    };

    setCurrentEpisode(restored);

    const audioSourceEl = document.getElementById('audioSource');
    if (audioSourceEl) {
      audioSourceEl.setAttribute('src', restored.mp3url || '');
    }
    player.load();
    player.currentTime = session.currentTime || 0;

    if (session.isPlaying) {
      const playPromise = player.play();
      if (playPromise && typeof playPromise.catch === 'function') {
        playPromise.catch(() => {});
      }
      applyButtonState(true);
    } else {
      player.pause();
      applyButtonState(false);
    }

    const controlBar = document.getElementById('audioControlBar');
    if (controlBar) {
      controlBar.style.display = 'flex';
    }
    document.body.classList.add('audio-playing');
    scheduleAudioBarRefresh();

    if (typeof PlayQueue !== 'undefined') {
      PlayQueue.setCurrent(restored, { enqueueIfMissing: false });
      renderQueuePanel(getQueueState());
    }

    updatePlaybackLabels(restored);
  }

  function init(options) {
    const configOptions = options || {};
    defaultDocumentTitle = configOptions.defaultTitle || document.title;
    config.onQueueAdvance = typeof configOptions.onQueueAdvance === 'function'
      ? configOptions.onQueueAdvance
      : null;

    if (initialised) {
      return;
    }

    initialised = true;
    hydrateQueueElements();
    bindQueuePanelEvents();
    attachAudioListeners();

    window.addEventListener('tma-playqueue-updated', handleQueueUpdated);
    window.addEventListener('resize', scheduleAudioBarRefresh);

    renderQueuePanel(getQueueState());
    initialiseFromSession();
    updatePlaybackLabels(getCurrentPlaybackMetadata());
    scheduleAudioBarRefresh();
  }

  const api = {
    init,
    showToast,
    buildEpisodePayload,
    scheduleAudioBarRefresh,
    renderQueuePanel,
    toggleQueuePanel,
    getQueueState,
    startPlayback,
    toggleAudioPlayPause,
    seekAudio,
    reopenPlayer,
    getCurrentPlaybackMetadata,
    updatePlaybackLabels,
    savePlayerSession,
    loadPlayerSession,
    clearPlayerSession,
  };

  window.PlayerUI = api;
  window.showToast = showToast;
  window.buildEpisodePayload = buildEpisodePayload;
  window.renderQueuePanel = renderQueuePanel;
  window.toggleQueuePanel = toggleQueuePanel;
  window.getQueueState = getQueueState;
  window.startPlayback = startPlayback;
  window.toggleAudioPlayPause = toggleAudioPlayPause;
  window.seekAudio = seekAudio;
  window.reopenPlayer = reopenPlayer;
  window.scheduleAudioBarRefresh = scheduleAudioBarRefresh;
})(window, document);
