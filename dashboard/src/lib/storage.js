
const STORAGE_BY_KIND = {
  local: () => globalThis.localStorage,
  session: () => globalThis.sessionStorage,
};

function resolveStorage(kind = 'local') {
  try {
    return STORAGE_BY_KIND[kind]?.() || null;
  } catch {
    return null;
  }
}

export function readStoredJson(key, fallback, { kind = 'local', validate } = {}) {
  const storage = resolveStorage(kind);
  if (!storage) return fallback;
  try {
    const raw = storage.getItem(key);
    if (raw == null) return fallback;
    const parsed = JSON.parse(raw);
    return !validate || validate(parsed) ? parsed : fallback;
  } catch {
    return fallback;
  }
}

export function writeStoredJson(key, value, { kind = 'local' } = {}) {
  const storage = resolveStorage(kind);
  if (!storage) return false;
  try {
    storage.setItem(key, JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
}

export function removeStoredValue(key, { kind = 'local' } = {}) {
  const storage = resolveStorage(kind);
  if (!storage) return false;
  try {
    storage.removeItem(key);
    return true;
  } catch {
    return false;
  }
}

export function subscribeStoredJson(key, listener, { kind = 'local', validate } = {}) {
  if (typeof window === 'undefined' || typeof window.addEventListener !== 'function') return () => {};
  const onStorage = (event) => {
    if (event.storageArea !== resolveStorage(kind) || event.key !== key) return;
    if (event.newValue == null) {
      listener(null);
      return;
    }
    try {
      const value = JSON.parse(event.newValue);
      if (!validate || validate(value)) listener(value);
    } catch {
      // Ignore corrupt writes from another tab.
    }
  };
  window.addEventListener('storage', onStorage);
  return () => window.removeEventListener('storage', onStorage);
}
