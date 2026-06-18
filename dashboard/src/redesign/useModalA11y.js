import { useEffect, useRef } from 'react';

// Accessibility for modal dialogs: move focus into the dialog on open, keep
// Tab/Shift+Tab cycling inside it (focus trap), close on Escape, and restore
// focus to the previously-focused element on close. Returns a ref to attach to
// the dialog panel element.
export function useModalA11y(onClose) {
  const ref = useRef(null);

  // Keep a ref to the latest onClose so the keydown handler always calls the
  // current callback without being listed as an effect dependency. Without this
  // pattern, callers that pass a fresh inline lambda on every render (e.g.
  // `() => setEditClip(null)`) would cause the effect to re-run — and reset
  // focus to the first focusable element — on every parent re-render while the
  // modal is open (e.g. every toast that appears).
  const onCloseRef = useRef(onClose);
  useEffect(() => { onCloseRef.current = onClose; }, [onClose]);

  useEffect(() => {
    const panel = ref.current;
    const prevActive = document.activeElement;

    const focusables = () =>
      panel
        ? Array.from(
            panel.querySelectorAll(
              'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'
            )
          ).filter((el) => el.offsetParent !== null)
        : [];

    // Move focus into the dialog (first focusable, else the panel itself).
    const first = focusables()[0];
    if (first) first.focus();
    else if (panel) { panel.setAttribute('tabindex', '-1'); panel.focus(); }

    const onKey = (e) => {
      if (e.key === 'Escape') { onCloseRef.current?.(); return; }
      if (e.key !== 'Tab') return;
      const items = focusables();
      if (items.length === 0) { e.preventDefault(); return; }
      const firstEl = items[0];
      const lastEl = items[items.length - 1];
      if (e.shiftKey && document.activeElement === firstEl) {
        e.preventDefault(); lastEl.focus();
      } else if (!e.shiftKey && document.activeElement === lastEl) {
        e.preventDefault(); firstEl.focus();
      }
    };

    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      // Restore focus to where it was before the modal opened.
      if (prevActive && typeof prevActive.focus === 'function') prevActive.focus();
    };
  }, []); // run once on mount — onClose changes are handled via onCloseRef above

  return ref;
}
