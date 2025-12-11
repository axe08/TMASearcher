(function (window, document) {
  'use strict';

  const STORAGE_SESSION_KEY = 'lastPlayerSession';
  const PROGRESS_PREFIX = 'progress-';
  const PLAYBACK_SPEED_KEY = 'playbackSpeed';

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
  let currentPlaybackSpeed = 1;
  let progressUpdateRaf = null;
  let isSeekingProgress = false;
  const queueDragState = {
    id: null,
  };

  // Stream tracking de-duplication state
  const streamTracking = {
    lastTrackedTime: new Map(),
    cooldownMs: 300000, // 5 minutes
  };

  function shouldTrackStream(episodeId) {
    if (!episodeId) return false;
    const now = Date.now();
    const lastTracked = streamTracking.lastTrackedTime.get(String(episodeId));
    if (!lastTracked) {
      return true; // Never tracked
    }
    // Only track again if cooldown has passed
    return (now - lastTracked) > streamTracking.cooldownMs;
  }

  function markStreamTracked(episodeId) {
    if (!episodeId) return;
    streamTracking.lastTrackedTime.set(String(episodeId), Date.now());
  }

  function trackStream(episodeId, podcastName) {
    if (!episodeId) return Promise.resolve(false);

    const podcast = podcastName || 'TMA';

    if (!shouldTrackStream(episodeId)) {
      return Promise.resolve(false); // Already tracked recently
    }

    return fetch(`/api/stream/${episodeId}?podcast_name=${podcast}`, { method: 'POST' })
      .then(response => {
        if (response.ok) {
          markStreamTracked(episodeId);
          return true;
        }
        return false;
      })
      .catch(err => {
        console.error('Stream tracking failed:', err);
        return false;
      });
  }

  function cloneEpisode(episode) {
    return episode ? { ...episode } : null;
  }

  function coerceEpisodeId(value) {
    if (value === null || value === undefined) {
      return value;
    }
    const numeric = Number(value);
    return Number.isNaN(numeric) ? value : numeric;
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

  function formatTime(seconds) {
    if (!seconds || isNaN(seconds)) {
      return '0:00';
    }
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  }

  function loadPlaybackSpeed() {
    try {
      const saved = localStorage.getItem(PLAYBACK_SPEED_KEY);
      if (saved) {
        const speed = parseFloat(saved);
        if (speed >= 0.5 && speed <= 2.5) {
          return speed;
        }
      }
    } catch (err) {
      console.warn('Unable to load playback speed', err);
    }
    return 1;
  }

  function savePlaybackSpeed(speed) {
    try {
      localStorage.setItem(PLAYBACK_SPEED_KEY, String(speed));
    } catch (err) {
      console.warn('Unable to save playback speed', err);
    }
  }

  function setPlaybackSpeed(speed) {
    const player = ensureAudioPlayer();
    if (!player) {
      return;
    }

    const validSpeed = Math.max(0.5, Math.min(2.5, parseFloat(speed) || 1));
    currentPlaybackSpeed = validSpeed;
    player.playbackRate = validSpeed;
    // Don't persist speed - each episode starts fresh at 1x

    // Update UI
    document.querySelectorAll('.speed-btn').forEach((btn) => {
      const btnSpeed = parseFloat(btn.dataset.speed);
      btn.classList.toggle('active', btnSpeed === validSpeed);
    });

    const controlBarSpeed = document.getElementById('controlBarSpeed');
    if (controlBarSpeed) {
      controlBarSpeed.textContent = `${validSpeed}×`;
      // Highlight when speed is not normal (1x)
      if (validSpeed !== 1) {
        controlBarSpeed.style.color = '#ff9800';
        controlBarSpeed.style.fontWeight = 'bold';
      } else {
        controlBarSpeed.style.color = '';
        controlBarSpeed.style.fontWeight = '';
      }
    }

    if (typeof umami !== 'undefined') {
      umami.track('playback_speed_changed', { speed: validSpeed });
    }
  }

  // Available playback speeds for cycling
  const PLAYBACK_SPEEDS = [0.75, 1, 1.25, 1.5, 1.75, 2];

  function cyclePlaybackSpeed() {
    const currentIndex = PLAYBACK_SPEEDS.indexOf(currentPlaybackSpeed);
    let nextIndex;

    if (currentIndex === -1) {
      // If current speed isn't in the list, go to 1x
      nextIndex = PLAYBACK_SPEEDS.indexOf(1);
    } else {
      // Cycle to next speed, wrap around to beginning
      nextIndex = (currentIndex + 1) % PLAYBACK_SPEEDS.length;
    }

    setPlaybackSpeed(PLAYBACK_SPEEDS[nextIndex]);
  }

  function updateMediaSession(metadata) {
    if (!('mediaSession' in navigator)) {
      return;
    }

    if (!metadata || !metadata.id) {
      navigator.mediaSession.metadata = null;
      return;
    }

    try {
      navigator.mediaSession.metadata = new MediaMetadata({
        title: metadata.title || 'Untitled Episode',
        artist: 'The Morning After',
        album: metadata.date || '',
        artwork: [
          { src: '/static/images/tma-icon-96.png', sizes: '96x96', type: 'image/png' },
          { src: '/static/images/tma-icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/static/images/tma-icon-512.png', sizes: '512x512', type: 'image/png' },
        ],
      });

      navigator.mediaSession.setActionHandler('play', () => {
        const player = ensureAudioPlayer();
        if (player) {
          player.play();
        }
      });

      navigator.mediaSession.setActionHandler('pause', () => {
        const player = ensureAudioPlayer();
        if (player) {
          player.pause();
        }
      });

      navigator.mediaSession.setActionHandler('seekbackward', () => {
        seekAudio(-30);
      });

      navigator.mediaSession.setActionHandler('seekforward', () => {
        seekAudio(30);
      });

      navigator.mediaSession.setActionHandler('previoustrack', () => {
        seekAudio(-30);
      });

      navigator.mediaSession.setActionHandler('nexttrack', () => {
        if (typeof PlayQueue !== 'undefined') {
          const nextEpisode = PlayQueue.next();
          if (nextEpisode) {
            handleQueueAdvance(nextEpisode);
          }
        }
      });
    } catch (err) {
      console.warn('Media Session API error:', err);
    }
  }

  function updateProgressBar() {
    const player = ensureAudioPlayer();
    if (!player || isSeekingProgress) {
      return;
    }

    const currentTime = player.currentTime || 0;
    const duration = player.duration || 0;

    // Update time displays
    const currentTimeDisplay = document.getElementById('currentTimeDisplay');
    const totalTimeDisplay = document.getElementById('totalTimeDisplay');
    const controlBarCurrentTime = document.getElementById('controlBarCurrentTime');
    const controlBarTotalTime = document.getElementById('controlBarTotalTime');

    if (currentTimeDisplay) {
      currentTimeDisplay.textContent = formatTime(currentTime);
    }
    if (totalTimeDisplay) {
      totalTimeDisplay.textContent = formatTime(duration);
    }
    if (controlBarCurrentTime) {
      controlBarCurrentTime.textContent = formatTime(currentTime);
    }
    if (controlBarTotalTime) {
      controlBarTotalTime.textContent = formatTime(duration);
    }

    // Update progress bars
    if (duration > 0) {
      const progress = (currentTime / duration) * 100;
      const progressFill = document.getElementById('progressBarFill');
      const controlBarProgressFill = document.getElementById('controlBarProgressFill');

      if (progressFill) {
        progressFill.style.width = `${progress}%`;
      }
      if (controlBarProgressFill) {
        controlBarProgressFill.style.width = `${progress}%`;
      }

      // Update handle position
      const progressHandle = document.getElementById('progressBarHandle');
      if (progressHandle) {
        progressHandle.style.left = `${progress}%`;
      }
    }

    // Update buffered progress
    if (player.buffered && player.buffered.length > 0 && duration > 0) {
      const buffered = player.buffered.end(player.buffered.length - 1);
      const bufferedProgress = (buffered / duration) * 100;
      const progressBuffered = document.getElementById('progressBarBuffered');
      if (progressBuffered) {
        progressBuffered.style.width = `${bufferedProgress}%`;
      }
    }
  }

  function scheduleProgressUpdate() {
    if (progressUpdateRaf) {
      cancelAnimationFrame(progressUpdateRaf);
    }
    progressUpdateRaf = requestAnimationFrame(() => {
      updateProgressBar();
      progressUpdateRaf = null;
    });
  }

  function seekToProgress(event) {
    const progressContainer = document.getElementById('progressContainer');
    if (!progressContainer) {
      return;
    }

    const rect = progressContainer.querySelector('.progress-bar-wrapper').getBoundingClientRect();
    const offsetX = event.clientX - rect.left;
    const percentage = Math.max(0, Math.min(1, offsetX / rect.width));

    const player = ensureAudioPlayer();
    if (player && player.duration) {
      player.currentTime = percentage * player.duration;
      updateProgressBar();
      persistProgress();

      if (typeof umami !== 'undefined') {
        umami.track('seeked_progress', { percentage: Math.round(percentage * 100) });
      }
    }
  }

  function showLoadingIndicator() {
    const loadingIndicator = document.getElementById('audioLoadingIndicator');
    const errorState = document.getElementById('audioErrorState');
    if (loadingIndicator) {
      loadingIndicator.style.display = 'flex';
    }
    if (errorState) {
      errorState.style.display = 'none';
    }
  }

  function hideLoadingIndicator() {
    const loadingIndicator = document.getElementById('audioLoadingIndicator');
    if (loadingIndicator) {
      loadingIndicator.style.display = 'none';
    }
  }

  function showErrorState() {
    const loadingIndicator = document.getElementById('audioLoadingIndicator');
    const errorState = document.getElementById('audioErrorState');
    if (loadingIndicator) {
      loadingIndicator.style.display = 'none';
    }
    if (errorState) {
      errorState.style.display = 'flex';
    }
  }

  function retryAudio() {
    if (currentEpisode) {
      startPlayback(currentEpisode, { openModal: false, resumeProgress: true });
    }
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

  function resetQueueDragState() {
    queueDragState.id = null;
  }

  function clearQueueDragIndicators() {
    if (!queueElements.list) {
      return;
    }
    queueElements.list.querySelectorAll('.play-queue-item').forEach((item) => {
      item.classList.remove('dragging', 'drag-over-top', 'drag-over-bottom');
      delete item.dataset.dropPosition;
    });
  }

  function handleQueueDragStart(event) {
    const item = event.currentTarget;
    const id = coerceEpisodeId(item.dataset.id);
    if (!id && id !== 0) {
      return;
    }
    queueDragState.id = id;
    item.classList.add('dragging');
    if (event.dataTransfer) {
      event.dataTransfer.effectAllowed = 'move';
      event.dataTransfer.setData('text/plain', String(id));
    }
  }

  function handleQueueDragOver(event) {
    if (!queueDragState.id && queueDragState.id !== 0) {
      return;
    }
    event.preventDefault();
    const item = event.currentTarget;
    const targetId = coerceEpisodeId(item.dataset.id);
    if (targetId === queueDragState.id) {
      return;
    }
    if (event.dataTransfer) {
      event.dataTransfer.dropEffect = 'move';
    }

    const rect = item.getBoundingClientRect();
    const offsetY = event.clientY - rect.top;
    const position = offsetY < rect.height / 2 ? 'before' : 'after';

    item.classList.remove('drag-over-top', 'drag-over-bottom');
    if (position === 'before') {
      item.classList.add('drag-over-top');
    } else {
      item.classList.add('drag-over-bottom');
    }
    item.dataset.dropPosition = position;
  }

  function handleQueueDragLeave(event) {
    const item = event.currentTarget;
    item.classList.remove('drag-over-top', 'drag-over-bottom');
    delete item.dataset.dropPosition;
  }

  function handleQueueDrop(event) {
    event.preventDefault();
    const item = event.currentTarget;
    const draggedId = queueDragState.id;
    const targetId = coerceEpisodeId(item.dataset.id);
    const dropPosition = item.dataset.dropPosition === 'after' ? 'after' : 'before';
    clearQueueDragIndicators();

    if ((draggedId || draggedId === 0) && (targetId || targetId === 0) && draggedId !== targetId) {
      if (typeof PlayQueue !== 'undefined' && typeof PlayQueue.reorder === 'function') {
        const queueItems = PlayQueue.getQueue();
        const draggedIndex = queueItems.findIndex((episode) => coerceEpisodeId(episode.id) === draggedId);
        let targetIndex = queueItems.findIndex((episode) => coerceEpisodeId(episode.id) === targetId);

        if (draggedIndex !== -1 && targetIndex !== -1) {
          if (dropPosition === 'after') {
            targetIndex += 1;
          }
          if (draggedIndex < targetIndex) {
            targetIndex -= 1;
          }

          const boundedIndex = Math.max(0, Math.min(queueItems.length - 1, targetIndex));
          if (boundedIndex !== draggedIndex) {
            PlayQueue.reorder(draggedId, boundedIndex);
            renderQueuePanel(PlayQueue.getState());
            scheduleAudioBarRefresh();
          }
        }
      }
    }

    resetQueueDragState();
  }

  function handleQueueDragEnd() {
    clearQueueDragIndicators();
    resetQueueDragState();
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

    const totalQueueItems = Array.isArray(queue) ? queue.length : 0;

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

    let queueIndexCounter = 0;

    entries.forEach((episode) => {
      const itemEl = document.createElement('div');
      itemEl.className = 'play-queue-item' + (episode.isCurrent ? ' active' : '');
      if (typeof episode.id !== 'undefined') {
        itemEl.dataset.id = episode.id;
      }
      if (episode.isCurrent) {
        itemEl.dataset.isCurrent = 'true';
      }

      const handleEl = document.createElement('div');
      handleEl.className = 'play-queue-handle';
      handleEl.setAttribute('draggable', 'false');
      handleEl.setAttribute('aria-hidden', 'true');
      handleEl.innerHTML = '<i class="fas fa-grip-vertical" aria-hidden="true"></i>';
      if (episode.isCurrent) {
        handleEl.classList.add('play-queue-handle-disabled');
      } else {
        handleEl.title = 'Drag to reorder';
      }
      itemEl.appendChild(handleEl);

      const infoEl = document.createElement('div');
      infoEl.className = 'play-queue-info';

      let titleEl;
      if (typeof episode.id !== 'undefined' && episode.id !== null) {
        titleEl = document.createElement('a');
        titleEl.href = `/episode/${episode.id}`;
        titleEl.className = 'play-queue-title';
        titleEl.textContent = episode.title;
        titleEl.setAttribute('draggable', 'false');
      } else {
        titleEl = document.createElement('div');
        titleEl.className = 'play-queue-title';
        titleEl.textContent = episode.title;
      }

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
        playBtn.setAttribute('draggable', 'false');
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
      removeBtn.setAttribute('draggable', 'false');
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

      if (!episode.isCurrent) {
        const isFirstQueueItem = queueIndexCounter === 0;
        const isLastQueueItem = queueIndexCounter === totalQueueItems - 1;

        itemEl.dataset.queueIndex = String(queueIndexCounter);
        queueIndexCounter += 1;
        itemEl.classList.add('queue-draggable');
        itemEl.setAttribute('draggable', 'true');
        itemEl.addEventListener('dragstart', handleQueueDragStart);
        itemEl.addEventListener('dragover', handleQueueDragOver);
        itemEl.addEventListener('dragleave', handleQueueDragLeave);
        itemEl.addEventListener('drop', handleQueueDrop);
        itemEl.addEventListener('dragend', handleQueueDragEnd);

        const reorderEl = document.createElement('div');
        reorderEl.className = 'play-queue-reorder';

        const moveUpBtn = document.createElement('button');
        moveUpBtn.type = 'button';
        moveUpBtn.className = 'play-queue-reorder-btn';
        moveUpBtn.innerHTML = '<i class="fas fa-chevron-up" aria-hidden="true"></i><span class="sr-only">Move up</span>';
        moveUpBtn.title = 'Move up';
        moveUpBtn.disabled = isFirstQueueItem;
        moveUpBtn.addEventListener('click', (event) => {
          event.stopPropagation();
          if (!moveUpBtn.disabled && typeof PlayQueue !== 'undefined') {
            const updatedState = PlayQueue.move(episode.id, -1);
            renderQueuePanel(updatedState);
          }
        });
        reorderEl.appendChild(moveUpBtn);

        const moveDownBtn = document.createElement('button');
        moveDownBtn.type = 'button';
        moveDownBtn.className = 'play-queue-reorder-btn';
        moveDownBtn.innerHTML = '<i class="fas fa-chevron-down" aria-hidden="true"></i><span class="sr-only">Move down</span>';
        moveDownBtn.title = 'Move down';
        moveDownBtn.disabled = isLastQueueItem;
        moveDownBtn.addEventListener('click', (event) => {
          event.stopPropagation();
          if (!moveDownBtn.disabled && typeof PlayQueue !== 'undefined') {
            const updatedState = PlayQueue.move(episode.id, 1);
            renderQueuePanel(updatedState);
          }
        });
        reorderEl.appendChild(moveDownBtn);

        actionsEl.appendChild(reorderEl);
      } else {
        itemEl.setAttribute('draggable', 'false');
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

  // Track playback milestones
  const playbackMilestones = {};

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

    // Track playback completion at 75% threshold
    if (player.duration && player.currentTime) {
      const progress = (player.currentTime / player.duration) * 100;
      const episodeKey = currentEpisode.id;

      if (!playbackMilestones[episodeKey]) {
        playbackMilestones[episodeKey] = { tracked75: false };
      }

      if (progress >= 75 && !playbackMilestones[episodeKey].tracked75) {
        playbackMilestones[episodeKey].tracked75 = true;
        if (typeof umami !== 'undefined') {
          umami.track('playback_completed', {
            episode_title: currentEpisode.title,
            episode_date: currentEpisode.date,
            completion_percent: 75
          });
        }
      }
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
    hideLoadingIndicator();

    const audioSourceEl = document.getElementById('audioSource');
    if (audioSourceEl) {
      audioSourceEl.setAttribute('src', episode.mp3url || '');
    }
    player.load();

    // Always start at normal speed (1x) - don't persist across episodes
    currentPlaybackSpeed = 1;
    player.playbackRate = 1;
    setPlaybackSpeed(1);

    if (playbackOptions.resumeProgress) {
      const saved = localStorage.getItem(`${PROGRESS_PREFIX}${episode.id}`);
      if (saved) {
        player.currentTime = parseFloat(saved);
      }
    }

    const playPromise = player.play();
    if (playPromise && typeof playPromise.catch === 'function') {
      playPromise.catch((error) => {
        console.error('Playback failed:', error);
        showErrorState();
      });
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
    updateMediaSession(episode);

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
    updateProgressBar();
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

    player.addEventListener('timeupdate', () => {
      persistProgress();
      scheduleProgressUpdate();
    });
    player.addEventListener('play', handleAudioPlay);
    player.addEventListener('pause', handleAudioPause);
    player.addEventListener('ended', handleAudioEnded);

    // Loading states
    player.addEventListener('loadstart', () => {
      showLoadingIndicator();
    });

    player.addEventListener('waiting', () => {
      showLoadingIndicator();
    });

    player.addEventListener('canplay', () => {
      hideLoadingIndicator();
    });

    player.addEventListener('loadedmetadata', () => {
      console.log('Audio metadata loaded, duration:', player.duration);
      updateProgressBar();
    });

    player.addEventListener('progress', () => {
      updateProgressBar();
    });

    player.addEventListener('durationchange', () => {
      updateProgressBar();
    });

    // Error handling
    player.addEventListener('error', (event) => {
      console.error('Audio error:', event);
      hideLoadingIndicator();
      showErrorState();

      if (typeof umami !== 'undefined') {
        umami.track('playback_error', {
          episode_title: currentEpisode?.title || 'Unknown',
          error_code: player.error?.code || 'unknown'
        });
      }
    });

    // Add click handler for progress bar
    const progressContainer = document.getElementById('progressContainer');
    if (progressContainer) {
      const wrapper = progressContainer.querySelector('.progress-bar-wrapper');
      if (wrapper) {
        wrapper.addEventListener('click', seekToProgress);
      }
    }
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

  function bindModalEvents() {
    // Listen for Bootstrap modal events to toggle body class
    const playerModal = document.getElementById('audioPlayerModal');
    if (!playerModal) {
      return;
    }

    // Use jQuery events for Bootstrap 4 modals
    if (typeof $ !== 'undefined' && window.$) {
      $(playerModal).on('show.bs.modal', function() {
        document.body.classList.add('player-modal-open');
        scheduleAudioBarRefresh();
      });

      $(playerModal).on('hidden.bs.modal', function() {
        document.body.classList.remove('player-modal-open');
        scheduleAudioBarRefresh();
      });
    } else {
      // Fallback for native Bootstrap 5 or vanilla JS
      playerModal.addEventListener('show.bs.modal', function() {
        document.body.classList.add('player-modal-open');
        scheduleAudioBarRefresh();
      });

      playerModal.addEventListener('hidden.bs.modal', function() {
        document.body.classList.remove('player-modal-open');
        scheduleAudioBarRefresh();
      });
    }
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
    bindModalEvents();
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
    setPlaybackSpeed,
    retryAudio,
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
  window.setPlaybackSpeed = setPlaybackSpeed;
  window.cyclePlaybackSpeed = cyclePlaybackSpeed;
  window.retryAudio = retryAudio;
  window.updateProgressBar = updateProgressBar;
  window.trackStream = trackStream;
  window.shouldTrackStream = shouldTrackStream;
  window.markStreamTracked = markStreamTracked;
})(window, document);
