// Icon — maps the prototype's kebab-case lucide names to lucide-react
// components (v0.344 has no DynamicIcon, so we map explicitly). Social marks
// (TikTok/Instagram/YouTube) come from the Simple Icons CDN, matching the
// prototype.
import {
  // lucide-react 0.344 predates the icon rename; alias the three renamed ones.
  Wand2 as WandSparkles, CheckCircle as CircleCheck, AlertTriangle as TriangleAlert,
  Clock, Settings, Check, Link, Square, Layers, Globe, FileUp,
  Clipboard, FileVideo, Upload, Sparkles, ScanFace, Scissors, ZoomIn, Languages,
  Captions, Type, SlidersHorizontal, Crop, Flame, UserRound, Mic, Plus, ArrowLeft,
  Download, Send, TrendingUp, Play, CheckSquare, X, AudioLines, CalendarClock,
  CalendarCheck, PartyPopper, Loader, Trash2, ChevronRight, Eye, EyeOff, KeyRound,
  Rss, Cookie, Info, Star,
} from 'lucide-react';

const MAP = {
  'wand-sparkles': WandSparkles, clock: Clock, settings: Settings, check: Check,
  link: Link, square: Square, layers: Layers, globe: Globe, 'file-up': FileUp,
  clipboard: Clipboard, 'file-video': FileVideo, upload: Upload, sparkles: Sparkles,
  'scan-face': ScanFace, scissors: Scissors, 'zoom-in': ZoomIn, languages: Languages,
  captions: Captions, type: Type, 'sliders-horizontal': SlidersHorizontal, crop: Crop,
  flame: Flame, 'user-round': UserRound, mic: Mic, plus: Plus, 'arrow-left': ArrowLeft,
  download: Download, send: Send, 'trending-up': TrendingUp, play: Play,
  'check-square': CheckSquare, x: X, 'audio-lines': AudioLines,
  'calendar-clock': CalendarClock, 'calendar-check': CalendarCheck,
  'party-popper': PartyPopper, loader: Loader, 'trash-2': Trash2,
  'chevron-right': ChevronRight, eye: Eye, 'eye-off': EyeOff, 'key-round': KeyRound,
  rss: Rss, cookie: Cookie, 'circle-check': CircleCheck, 'triangle-alert': TriangleAlert,
  info: Info, star: Star,
};

export function Icon({ n, cls, style }) {
  const C = MAP[n] || Square;
  // lucide-react renders an <svg>; the design's CSS sizes svgs per context.
  return <C className={cls} style={style} />;
}

// Brand/social marks via Simple Icons CDN (lucide dropped these).
// `n` is constrained to a known allow-list so a caller can never inject an
// arbitrary slug (or scheme) into the CDN URL — only these three marks exist.
const SOCIAL_SLUGS = new Set(['tiktok', 'instagram', 'youtube']);
const SAFE_COLOR_RE = /^[a-zA-Z0-9]+$/;

export function Social({ n, color = 'white', size = 15, style }) {
  if (!SOCIAL_SLUGS.has(n)) return null;
  const safeColor = SAFE_COLOR_RE.test(color) ? color : 'white';
  return (
    <img
      src={`https://cdn.simpleicons.org/${n}/${safeColor}`}
      width={size}
      height={size}
      alt={n}
      style={{ display: 'block', ...style }}
    />
  );
}
