
import { forwardRef, useEffect, useRef, useState } from 'react';

export const LazyVideo = forwardRef(function LazyVideo({ src, rootMargin = '320px', className, style, ...props }, forwardedRef) {
  const localRef = useRef(null);
  const [active, setActive] = useState(false);

  useEffect(() => {
    const node = localRef.current;
    if (!node || !src) return undefined;
    if (typeof IntersectionObserver === 'undefined') {
      setActive(true);
      return undefined;
    }
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        setActive(true);
        observer.disconnect();
      }
    }, { rootMargin });
    observer.observe(node);
    return () => observer.disconnect();
  }, [rootMargin, src]);

  const assignRef = (node) => {
    localRef.current = node;
    if (typeof forwardedRef === 'function') forwardedRef(node);
    else if (forwardedRef) forwardedRef.current = node;
  };

  return (
    // Captions are burned into ClippyMe output pixels; there is no separate text track.
    // eslint-disable-next-line jsx-a11y/media-has-caption
    <video
      {...props}
      ref={assignRef}
      className={className}
      style={style}
      src={active ? src : undefined}
      data-src={active ? undefined : src}
      preload={active ? (props.preload || 'metadata') : 'none'}
    />
  );
});
