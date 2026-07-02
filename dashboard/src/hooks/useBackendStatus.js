import { useState, useEffect } from 'react';
import { getApiUrl } from '../config';
import { apiFetch } from '../lib/apiToken';

/**
 * Fetches one-off backend config flags on mount:
 * - whether HF_TOKEN is set
 * - whether YouTube cookies are configured
 *
 * @returns {{ hfTokenSet: boolean, cookiesConfigured: boolean, setCookiesConfigured: (v: boolean) => void }}
 */
export function useBackendStatus() {
  const [hfTokenSet, setHfTokenSet] = useState(true); // assume set until checked
  const [cookiesConfigured, setCookiesConfigured] = useState(false);

  useEffect(() => {
    apiFetch(getApiUrl('/api/config'))
      .then((r) => (r.ok ? r.json() : {}))
      .then((data) => setHfTokenSet(!!data.HF_TOKEN))
      .catch(() => {});
  }, []);

  useEffect(() => {
    apiFetch(getApiUrl('/api/config/cookies/status'))
      .then((r) => (r.ok ? r.json() : {}))
      .then((data) => setCookiesConfigured(!!data.configured))
      .catch(() => {});
  }, []);

  return { hfTokenSet, setHfTokenSet, cookiesConfigured, setCookiesConfigured };
}
