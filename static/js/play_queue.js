(function (global) {
  const STORAGE_QUEUE_KEY = 'tma_play_queue';
  const STORAGE_CURRENT_KEY = 'tma_current_track';
  const STORAGE_UPDATED_KEY = 'tma_queue_updated_at';

  const defaultState = {
    queue: [],
    current: null,
  };

  let queue = [];
  let current = null;

  function safeParse(value, fallback) {
    if (!value) {
      return fallback;
    }
    try {
      return JSON.parse(value);
    } catch (err) {
      console.warn('Failed to parse queue storage item', err);
      return fallback;
    }
  }

  function loadState() {
    queue = safeParse(localStorage.getItem(STORAGE_QUEUE_KEY), defaultState.queue);
    current = safeParse(localStorage.getItem(STORAGE_CURRENT_KEY), defaultState.current);

    if (!Array.isArray(queue)) {
      queue = [];
    }

    if (current && !current.id) {
      current = null;
    }
  }

  function persistState() {
    try {
      localStorage.setItem(STORAGE_QUEUE_KEY, JSON.stringify(queue));
      if (current) {
        localStorage.setItem(STORAGE_CURRENT_KEY, JSON.stringify(current));
      } else {
        localStorage.removeItem(STORAGE_CURRENT_KEY);
      }
      localStorage.setItem(STORAGE_UPDATED_KEY, Date.now().toString());
    } catch (err) {
      console.warn('Unable to persist play queue', err);
    }
    broadcast();
  }

  function broadcast() {
    try {
      const event = new CustomEvent('tma-playqueue-updated', {
        detail: getState(),
      });
      global.dispatchEvent(event);
    } catch (err) {
      console.warn('Failed to dispatch play queue event', err);
    }
  }

  function cloneEpisode(episode) {
    return episode ? { ...episode } : null;
  }

  function normaliseEpisode(episode) {
    if (!episode || !episode.id) {
      return null;
    }
    return {
      id: episode.id,
      title: episode.title || 'Untitled Episode',
      date: episode.date || '',
      mp3url: episode.mp3url || '',
      url: episode.url || '',
      show_notes: episode.show_notes || '',
    };
  }

  function removeFromQueueById(id) {
    queue = queue.filter((item) => item.id !== id);
  }

  function add(episode, options = {}) {
    const normalised = normaliseEpisode(episode);
    if (!normalised) {
      return getState();
    }

    const { playNext = false } = options;

    if (current && current.id === normalised.id) {
      return getState();
    }

    const exists = queue.find((item) => item.id === normalised.id);
    if (exists) {
      if (playNext) {
        queue = [normalised, ...queue.filter((item) => item.id !== normalised.id)];
        persistState();
        // Track play next reorder
        if (typeof umami !== 'undefined') {
          umami.track('queue_play_next', {
            episode_title: normalised.title,
            episode_date: normalised.date,
            queue_size: queue.length
          });
        }
      }
      return getState();
    }

    queue = playNext ? [normalised, ...queue] : [...queue, normalised];
    persistState();

    // Track queue addition
    if (typeof umami !== 'undefined') {
      umami.track('queue_added', {
        episode_title: normalised.title,
        episode_date: normalised.date,
        position: playNext ? 'next' : 'end',
        queue_size: queue.length
      });
    }

    return getState();
  }

  function addAndPlayNext(episode) {
    return add(episode, { playNext: true });
  }

  function setCurrent(episode, options = {}) {
    const normalised = normaliseEpisode(episode);
    const { enqueueIfMissing = true } = options;

    if (!normalised) {
      current = null;
      persistState();
      return getState();
    }

    removeFromQueueById(normalised.id);

    current = normalised;

    if (enqueueIfMissing) {
      queue = queue.filter((item) => item.id !== normalised.id);
    }

    persistState();
    return getState();
  }

  function remove(id) {
    if (!id) {
      return getState();
    }

    const wasCurrent = current && current.id === id;
    const removedItem = wasCurrent ? current : queue.find((item) => item.id === id);

    removeFromQueueById(id);
    if (wasCurrent) {
      current = null;
    }

    // Track queue removal
    if (typeof umami !== 'undefined' && removedItem) {
      umami.track('queue_removed', {
        episode_title: removedItem.title,
        episode_date: removedItem.date,
        queue_size: queue.length
      });
    }

    persistState();
    return getState();
  }

  function clear() {
    queue = [];
    current = null;
    persistState();
    return getState();
  }

  function getQueue() {
    return queue.map(cloneEpisode);
  }

  function getCurrent() {
    return cloneEpisode(current);
  }

  function next() {
    if (!queue.length) {
      current = null;
      persistState();
      return null;
    }

    const [nextEpisode, ...rest] = queue;
    current = nextEpisode;
    queue = rest;
    persistState();
    return cloneEpisode(current);
  }

  function getState() {
    return {
      current: getCurrent(),
      queue: getQueue(),
    };
  }

  function contains(id) {
    if (!id) {
      return false;
    }
    if (current && current.id === id) {
      return true;
    }
    return queue.some((item) => item.id === id);
  }

  function move(id, direction) {
    const index = queue.findIndex((item) => item.id === id);
    if (index === -1) {
      return getState();
    }

    const newIndex = index + direction;
    if (newIndex < 0 || newIndex >= queue.length) {
      return getState();
    }

    const updated = [...queue];
    const [item] = updated.splice(index, 1);
    updated.splice(newIndex, 0, item);
    queue = updated;
    persistState();
    return getState();
  }

  function handleStorageEvent(event) {
    if (event.key === STORAGE_QUEUE_KEY || event.key === STORAGE_CURRENT_KEY || event.key === STORAGE_UPDATED_KEY) {
      loadState();
      broadcast();
    }
  }

  function init() {
    loadState();
    global.addEventListener('storage', handleStorageEvent);
    broadcast();
  }

  init();

  global.PlayQueue = {
    add,
    addAndPlayNext,
    remove,
    clear,
    getQueue,
    getCurrent,
    getState,
    setCurrent,
    next,
    contains,
    move,
  };
})(window);
