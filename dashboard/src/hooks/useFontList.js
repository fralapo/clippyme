// Live classic-subtitle font list: the curated SUB_FONTS labels merged with any
// faces the user has uploaded via Settings → Fonts (e.g. a licensed Stratos).
// Returns [value, label] pairs ready for a <select>. Falls back to the curated
// list alone if the backend can't be reached.
import { useEffect, useState } from 'react';
import { SUB_FONTS } from '../redesign/data';
import { listFonts } from '../redesign/realApi';

export function useFontList() {
  const [fonts, setFonts] = useState(SUB_FONTS);
  useEffect(() => {
    let alive = true;
    listFonts()
      .then(({ fonts: live }) => {
        if (!alive || !Array.isArray(live)) return;
        const known = new Set(SUB_FONTS.map(([v]) => v));
        const extra = live
          .filter((n) => n && !known.has(n))
          .map((n) => [n, n.replace(/-/g, ' ')]);
        if (extra.length) setFonts([...SUB_FONTS, ...extra]);
      })
      .catch(() => {});
    return () => { alive = false; };
  }, []);
  return fonts;
}
