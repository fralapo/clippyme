import { useState, useEffect } from 'react';
import { getApiUrl } from '../config';

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
    fetch(getApiUrl('/api/config'))
      .then((r) => (r.ok ? r.json() : {}))
      .then((data) => setHfTokenSet(!!data.HF_TOKEN))
      .catch(() => {});
  }, []);

  useEffect(() => {
    fetch(getApiUrl('/api/config/cookies/status'))
      .then((r) => (r.ok ? r.json() : {}))
      .then((data) => setCookiesConfigured(!!data.configured))
      .catch(() => {});
  }, []);

  return { hfTokenSet, setHfTokenSet, cookiesConfigured, setCookiesConfigured };
}
