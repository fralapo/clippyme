/**
 * Map backend log lines to a coarse pipeline step label for the UI spinner.
 *
 * @param {string[]} logs
 * @returns {'processing' | 'analyzing' | 'transcribing' | 'downloading' | 'queued' | null}
 */
export function detectPipelineStep(logs) {
  if (!logs || logs.length === 0) return null;
  const joined = logs.join(' ');
  if (
    joined.includes('Processing Clip') ||
    joined.includes('Step 4:') ||
    joined.includes('Step 5:') ||
    joined.includes('Step 6:')
  ) {
    return 'processing';
  }
  if (joined.includes('Analyzing with Gemini') || joined.includes('Gemini')) return 'analyzing';
  if (joined.includes('Transcribing') || joined.includes('Faster-Whisper')) return 'transcribing';
  if (joined.includes('Downloading') || joined.includes('yt-dlp')) return 'downloading';
  if (joined.includes('queued') || joined.includes('started')) return 'queued';
  return null;
}
