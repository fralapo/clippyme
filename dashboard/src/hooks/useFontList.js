// Live classic-subtitle font list: the curated SUB_FONTS labels merged with any
// faces the user has uploaded via Settings → Fonts (e.g. a licensed Stratos).
// Returns [value, label] pairs ready for a <select>. Falls back to the curated
// list alone if the backend can't be reached.
import { useEffect, useState } from 'react';
import { SUB_FONTS } from '../lib/uiOptions';
import { listFonts } from '../api/client';

// { fonts, live }: `live` turns true once the backend list has loaded. It then
// names every face the renderer can resolve (bundled + uploaded), so a font
// absent from `fonts` is no longer available (e.g. deleted in Settings). A
// failed or empty response (listFonts' error value; a real list always carries
// the bundled faces) leaves `live` false: availability unknown.
export function useFontCatalog() {
  const [catalog, setCatalog] = useState({ fonts: SUB_FONTS, live: false });
  useEffect(() => {
    let alive = true;
    listFonts()
      .then(({ fonts: live }) => {
        if (!alive || !Array.isArray(live) || !live.length) return;
        const known = new Set(SUB_FONTS.map(([v]) => v));
        const extra = live
          .filter((n) => n && !known.has(n))
          .map((n) => [n, n.replace(/-/g, ' ')]);
        setCatalog({ fonts: extra.length ? [...SUB_FONTS, ...extra] : SUB_FONTS, live: true });
      })
      .catch(() => {});
    return () => { alive = false; };
  }, []);
  return catalog;
}

export function useFontList() {
  return useFontCatalog().fonts;
}
