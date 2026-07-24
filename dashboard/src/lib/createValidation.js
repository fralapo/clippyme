
const MAX_BATCH_ITEMS = 20;
const MAX_FILE_BYTES = 16 * 1024 * 1024 * 1024;
const VIDEO_EXTENSIONS = /\.(mp4|mov|webm|mkv|m4v|avi)$/i;

const ALLOWED_HOSTS = new Set([
  'youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com',
  'youtu.be', 'www.youtu.be', 'youtube-nocookie.com', 'www.youtube-nocookie.com',
  'twitch.tv', 'www.twitch.tv', 'm.twitch.tv', 'clips.twitch.tv',
  'kick.com', 'www.kick.com',
]);

function validateUrl(value) {
  const raw = String(value || '').trim();
  if (!raw) return 'Add a video URL.';
  let url;
  try { url = new URL(raw); } catch { return 'Enter a valid absolute URL.'; }
  if (url.protocol !== 'https:') return 'Use an HTTPS URL.';
  if (url.username || url.password || url.port) return 'The URL cannot contain credentials or a custom port.';
  if (!ALLOWED_HOSTS.has(url.hostname.toLowerCase())) return 'Supported sources are YouTube, Twitch, and Kick.';
  return null;
}

function validateFile(file) {
  if (!file) return 'Choose a video file.';
  if (Number(file.size) > MAX_FILE_BYTES) return 'The file exceeds the 16 GB server limit.';
  const name = String(file.name || '');
  if (file.type && !String(file.type).startsWith('video/') && !VIDEO_EXTENSIONS.test(name)) {
    return 'Choose a supported video file.';
  }
  return null;
}

export function validateCreateOptions(opts = {}) {
  const errors = [];
  const mode = opts.mode === 'batch' ? 'batch' : 'single';
  let sourceCount = 0;
  let urls = [];

  if (mode === 'single') {
    sourceCount = 1;
    if (opts.source === 'file') {
      const error = validateFile(opts.file);
      if (error) errors.push(error);
    } else {
      const error = validateUrl(opts.url);
      if (error) errors.push(error);
      else urls = [String(opts.url).trim()];
    }
  } else {
    const rawUrls = String(opts.batch || '').split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
    const seen = new Set();
    urls = rawUrls.filter((url) => {
      if (seen.has(url)) return false;
      seen.add(url);
      return true;
    });
    const files = Array.isArray(opts.batchFiles) ? opts.batchFiles : [];
    sourceCount = urls.length + files.length;
    if (!sourceCount) errors.push('Add at least one URL or video file.');
    if (sourceCount > MAX_BATCH_ITEMS) errors.push(`A batch can contain at most ${MAX_BATCH_ITEMS} sources.`);
    urls.forEach((url, index) => {
      const error = validateUrl(url);
      if (error) errors.push(`URL ${index + 1}: ${error}`);
    });
    files.forEach((file, index) => {
      const error = validateFile(file);
      if (error) errors.push(`File ${index + 1}: ${error}`);
    });
  }

  return {
    valid: errors.length === 0,
    errors,
    firstError: errors[0] || '',
    sourceCount,
    urls,
  };
}

export { MAX_BATCH_ITEMS, MAX_FILE_BYTES };
