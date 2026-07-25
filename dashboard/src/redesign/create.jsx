// ClippyMe redesign — Create flow: presets + source + calm options recipe.
import { useState, useRef } from 'react';
import { Icon, Btn, Panel, Segmented, Switch, Stepper } from './primitives';
import { Hero } from './chrome';
import { LANGUAGES, GEMINI_MODELS, HOOK_STYLE_DEFAULT } from './data';
import { HookStyleControls, HookPreview } from './hookStyle';
import { SubtitleControls } from './subtitleControls';
import { LogoControls, GradeControls } from './layerControls';
import { BannerControls } from './bannerControls';
import { validateCreateOptions } from '../lib/createValidation';

function PresetCards({ presets, active, defaultId, onPick, onSetDefault, onDelete, onSaveCurrent }) {
  const corner = { position: 'absolute', top: 12, left: 12, display: 'flex', gap: 8, zIndex: 2 };
  return (
    <div className="preset-row">
      {presets.map((p) => (
        // role=button (not a real <button>) so the star/trash actions inside
        // can be real, keyboard-operable <button>s — interactive-in-interactive
        // is invalid HTML.
        <div key={p.id} role="button" tabIndex={0} aria-pressed={active === p.id} className={'preset' + (active === p.id ? ' on' : '')}
          onClick={() => onPick(p)}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onPick(p); } }}>
          <span className="pcheck"><Icon n="check" /></span>
          <span style={corner}>
            <button type="button" className="picon-btn"
              title={defaultId === p.id ? 'Default (click to unset)' : 'Set as default'}
              aria-label={defaultId === p.id ? 'Unset default preset' : 'Set as default preset'}
              onClick={(e) => { e.stopPropagation(); onSetDefault(p.id); }}
              style={{ color: defaultId === p.id ? 'var(--brand-amber)' : 'var(--fg-4)' }}>
              <Icon n="star" style={{ width: 14, height: 14 }} />
            </button>
            {p.user && (
              <button type="button" className="picon-btn" title="Delete preset" aria-label="Delete preset"
                onClick={(e) => { e.stopPropagation(); onDelete(p.id); }} style={{ color: 'var(--fg-4)' }}>
                <Icon n="trash-2" style={{ width: 14, height: 14 }} />
              </button>
            )}
          </span>
          <span className="pico"><Icon n={p.icon} /></span>
          <span className="pt">{p.title}{defaultId === p.id && <span style={{ color: 'var(--brand-amber)', fontSize: 11, marginLeft: 6 }}>· default</span>}</span>
          <span className="pd">{p.desc}</span>
        </div>
      ))}
      <button type="button" className="preset" onClick={onSaveCurrent}
        style={{ borderStyle: 'dashed', alignItems: 'center', justifyContent: 'center', textAlign: 'center' }}>
        <span className="pico"><Icon n="plus" /></span>
        <span className="pt">Save current</span>
        <span className="pd">Store these settings as your own preset</span>
      </button>
    </div>
  );
}

function SourcePanel({ opts, set }) {
  const [drag, setDrag] = useState(false);
  const fileInput = useRef(null);
  const batchInput = useRef(null);
  const batchLines = opts.batch.split('\n').filter((l) => l.trim());
  const batchFileCount = (opts.batchFiles || []).length;
  const totalQueued = batchLines.length + batchFileCount;
  const pickFile = (f) => f && set({ file: f, fileName: f.name });
  return (
    <Panel title="Source" sub="Paste a link or drop a file" icon="link"
      headRight={
        <Segmented value={opts.mode} onChange={(id) => set({ mode: id })}
          options={[{ id: 'single', label: 'Single', icon: 'square' }, { id: 'batch', label: 'Batch', icon: 'layers' }]} />
      }>
      {opts.mode === 'single' ? (
        <div>
          <Segmented full value={opts.source} onChange={(id) => set({ source: id })}
            options={[{ id: 'url', label: 'URL', icon: 'globe' }, { id: 'file', label: 'Upload', icon: 'file-up' }]} />
          <div style={{ height: 14 }} />
          {opts.source === 'url' ? (
            <div className="input">
              <Icon n="link" />
              <input value={opts.url} placeholder="Paste a video link (YouTube, Twitch, or Kick)"
                onChange={(e) => set({ url: e.target.value })} />
              <button type="button" className="paste" onClick={async () => {
                try {
                  const text = await navigator.clipboard.readText();
                  if (text) set({ url: text.trim() });
                } catch {
                  /* clipboard blocked (no permission / insecure context) — no-op */
                }
              }}>
                <Icon n="clipboard" />Paste
              </button>
            </div>
          ) : (
            <div className={'dropzone' + (opts.file ? ' has' : drag ? ' drag' : '')}
              role="button" tabIndex={0}
              aria-label={opts.file ? 'Remove selected video' : 'Choose a video file'}
              onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
              onDragLeave={() => setDrag(false)}
              onDrop={(e) => { e.preventDefault(); setDrag(false); pickFile(e.dataTransfer.files?.[0]); }}
              onClick={() => { if (opts.file) { set({ file: null, fileName: '' }); } else { fileInput.current?.click(); } }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.currentTarget.click(); }
              }}>
              <input ref={fileInput} type="file" accept="video/*,.mp4,.mov,.webm,.mkv,.m4v,.avi" hidden
                onChange={(e) => pickFile(e.target.files?.[0])} />
              <div className="dz-ico"><Icon n={opts.file ? 'file-video' : 'upload'} /></div>
              {opts.file ? (
                <div><b>{opts.fileName}</b><div className="label" style={{ marginTop: 6 }}>Ready · click to remove</div></div>
              ) : (
                <div>Drop a video or <b style={{ color: 'var(--brand-blue)' }}>browse</b>
                  <div className="label" style={{ marginTop: 6, textTransform: 'none', letterSpacing: 0 }}>MP4 · MOV · WEBM · up to 16&nbsp;GB</div></div>
              )}
            </div>
          )}
        </div>
      ) : (
        <div>
          <div className="field">
            <span className="field-label"><Icon n="globe" /> URLs · one per line</span>
            <textarea className="ta mono" rows="4" value={opts.batch}
              placeholder={'https://youtube.com/watch?v=a1\nhttps://youtube.com/watch?v=b2'}
              onChange={(e) => set({ batch: e.target.value })}></textarea>
          </div>
          <div className="field" style={{ marginBottom: 0 }}>
            <div className="dropzone" style={{ padding: 18 }}
              role="button" tabIndex={0} aria-label="Add video files to the batch"
              onClick={() => batchInput.current?.click()}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); batchInput.current?.click(); }
              }}>
              <input ref={batchInput} type="file" accept="video/*,.mp4,.mov,.webm,.mkv,.m4v,.avi" hidden multiple
                onChange={(e) => set({ batchFiles: [...(opts.batchFiles || []), ...Array.from(e.target.files || [])] })} />
              <Icon n="plus" style={{ width: 16, height: 16 }} /> &nbsp;Add files to the batch
            </div>
          </div>
          {batchFileCount > 0 && (
            <div className="s-sub" style={{ marginTop: 10 }}>
              {(opts.batchFiles || []).map((f, i) => (
                <span key={i} className="chip">{f.name.slice(0, 22)}</span>
              ))}
              <button type="button" className="chip" style={{ cursor: 'pointer', color: 'var(--danger)', background: 'none', border: 'none', font: 'inherit' }} onClick={() => set({ batchFiles: [] })}>clear files</button>
            </div>
          )}
          <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 14, paddingTop: 14, borderTop: '1px solid var(--line-1)' }}>
            <span className="label">Queued</span>
            <span className="label tnum" style={{ color: totalQueued > 20 ? 'var(--danger)' : totalQueued ? 'var(--brand-amber)' : 'var(--fg-4)' }}>
              {String(totalQueued).padStart(2, '0')} / 20
            </span>
          </div>
        </div>
      )}

      <div style={{ marginTop: 18, paddingTop: 18, borderTop: '1px solid var(--line-1)' }}>
        <div className="field" style={{ marginBottom: 0 }}>
          <span className="field-label"><Icon n="sparkles" style={{ color: 'var(--brand-blue)' }} /> AI instructions · optional</span>
          <textarea className="ta" rows="2" value={opts.instructions}
            placeholder="e.g. “Find the funniest moments” or “Skip the intro, focus on the demo”"
            onChange={(e) => set({ instructions: e.target.value })}></textarea>
        </div>
      </div>
    </Panel>
  );
}

function OptRow({ icon, label, desc, on, set, onConfig, configActive }) {
  return (
    <div className={'opt' + (on ? ' on' : '')}>
      <div className="oico"><Icon n={icon} /></div>
      <div className="otxt">
        <div className="ot">{label}</div>
        <div className="od">{desc}</div>
      </div>
      <div className="r">
        {onConfig && on && (
          <button type="button" className={'cfg' + (configActive ? ' active' : '')} onClick={onConfig} aria-label={'Configure ' + label}>
            <Icon n="sliders-horizontal" />
          </button>
        )}
        <Switch on={on} onChange={set} />
      </div>
    </div>
  );
}

// Adapter over the shared SubtitleControls: resolves the recipe's inline
// defaults into a fully-populated value object (the shared component never
// applies defaults) and reverse-maps the seedClipParams-vocabulary partials
// back onto the persisted sub* opts keys.
const SUB_KEYMAP = {
  mode: 'subMode', preset: 'subPreset', font: 'subFont', font_color: 'subColor',
  outline_color: 'subStroke', font_size: 'subFontSize', border_width: 'subOutlineW',
  bg: 'subBg', position: 'subPosition', align: 'subAlign', offset_y: 'subOffsetY',
};

function SubConfig({ opts, set }) {
  const value = {
    mode: opts.subMode,
    preset: opts.subPreset,
    font: opts.subFont || 'Montserrat-Black',
    font_color: opts.subColor || '#FFFFFF',
    outline_color: opts.subStroke || '#000000',
    font_size: opts.subFontSize || 0,
    border_width: opts.subOutlineW ?? 2,
    bg: !!opts.subBg,
    position: opts.subPosition || 'bottom',
    align: opts.subAlign || 'center',
    offset_y: opts.subOffsetY || 0,
  };
  const onChange = (partial) => {
    const patch = {};
    for (const [k, v] of Object.entries(partial)) patch[SUB_KEYMAP[k]] = v;
    set(patch);
  };
  return <SubtitleControls variant="create" value={value} onChange={onChange} />;
}

function HookConfig({ opts, set }) {
  const hs = opts.hookStyle || HOOK_STYLE_DEFAULT;
  const setStyle = (partial) => set({ hookStyle: { ...HOOK_STYLE_DEFAULT, ...hs, ...partial } });
  return (
    <div className="cfg-drawer fade-in">
      <HookPreview text="Your hook text" style={hs} />
      <div className="cf-row" style={{ marginTop: 12 }}>
        <span className="field-label" style={{ marginBottom: 9, display: 'flex' }}>Position</span>
        <Segmented full value={opts.hookPos} onChange={(id) => set({ hookPos: id })}
          options={[{ id: 'top', label: 'Top' }, { id: 'center', label: 'Center' }, { id: 'bottom', label: 'Bottom' }]} />
      </div>
      <div className="cf-row">
        <span className="field-label" style={{ marginBottom: 9, display: 'flex' }}>Size</span>
        <Segmented full value={opts.hookSize} onChange={(id) => set({ hookSize: id })}
          options={[{ id: 'S', label: 'Small' }, { id: 'M', label: 'Medium' }, { id: 'L', label: 'Large' }]} />
      </div>
      <HookStyleControls style={hs} set={setStyle} />
    </div>
  );
}

function LogoConfig({ opts, set }) {
  return (
    <div className="cfg-drawer fade-in">
      <LogoControls position={opts.logoPos || 'top-right'} size={opts.logoSize || 'M'}
        onChange={(p) => set(p.position !== undefined
          ? { logoPos: p.position } : { logoSize: p.size })} />
      <div className="od" style={{ marginTop: 2 }}>Upload your logo PNG in Settings → Brand logo.</div>
    </div>
  );
}

function BannerConfig({ opts, set }) {
  const value = {
    platform: opts.bannerPlatform || 'kick',
    handle: opts.bannerHandle || '',
    y_pct: opts.bannerYPct ?? 0.85,
  };
  const onChange = (partial) => {
    const patch = {};
    if (partial.platform !== undefined) patch.bannerPlatform = partial.platform;
    if (partial.handle !== undefined) patch.bannerHandle = partial.handle;
    if (partial.y_pct !== undefined) patch.bannerYPct = partial.y_pct;
    set(patch);
  };
  return (
    <div className="cfg-drawer fade-in">
      <BannerControls value={value} onChange={onChange} />
    </div>
  );
}

function OptionsPanel({ opts, set }) {
  const [subCfg, setSubCfg] = useState(false);
  const [hookCfg, setHookCfg] = useState(false);
  const [logoCfg, setLogoCfg] = useState(false);
  const [bannerCfg, setBannerCfg] = useState(false);
  return (
    <Panel title="Recipe" sub="What ClippyMe makes from each video" icon="sliders-horizontal">
      <div className="label" style={{ marginBottom: 4 }}>Output</div>
      <div className="opt">
        <div className="oico"><Icon n="scissors" /></div>
        <div className="otxt">
          <div className="ot">Clips per video</div>
          <div className="od">{opts.clipsAuto ? 'Auto · ClippyMe picks the best number for the video' : 'Aim for a rough target (a hint, not a hard cap)'}</div>
        </div>
        <div className="r" style={{ gap: 9 }}>
          {!opts.clipsAuto && <Stepper value={opts.clips} set={(v) => set({ clips: v })} />}
          <Segmented value={opts.clipsAuto ? 'auto' : 'custom'}
            onChange={(id) => set({ clipsAuto: id === 'auto' })}
            options={[{ id: 'auto', label: 'Auto' }, { id: 'custom', label: 'Set' }]} />
        </div>
      </div>
      <div className="opt">
        <div className="oico"><Icon n="crop" /></div>
        <div className="otxt"><div className="ot">Aspect ratio</div><div className="od">9:16 vertical · 1:1 square · 16:9 horizontal</div></div>
        <div className="r"><Segmented value={opts.aspect} onChange={(id) => set({ aspect: id })}
          options={[{ id: '9:16', label: '9:16' }, { id: '1:1', label: '1:1' }, { id: '16:9', label: '16:9' }]} /></div>
      </div>

      <div className="label" style={{ margin: '16px 0 4px' }}>AI &amp; reframe</div>
      <OptRow icon="sparkles" label="Find viral moments" desc="Gemini scores the transcript · off = whole video"
        on={opts.detect} set={(v) => set({ detect: v })} />
      {opts.detect && (
        <div className="opt">
          <div className="oico"><Icon n="sparkles" /></div>
          <div className="otxt" style={{ flex: 1 }}><div className="ot">Gemini model</div><div className="od">Override for this job · blank uses the Settings default</div></div>
          <div className="r" style={{ flex: '0 0 184px' }}>
            <select className="sel" value={opts.model || ''} onChange={(e) => set({ model: e.target.value })}>
              {GEMINI_MODELS.map(([v, l]) => <option key={v || 'default'} value={v}>{l}</option>)}
            </select>
          </div>
        </div>
      )}
      <div className="opt">
        <div className="oico"><Icon n="scan-face" /></div>
        <div className="otxt"><div className="ot">Reframe</div><div className="od">Auto face-track · Subject FrameShift crop · Off letterbox bands</div></div>
        <div className="r"><Segmented value={(opts.reframeMode === 'object' ? 'subject' : opts.reframeMode) || (opts.reframe === false ? 'disabled' : 'auto')} onChange={(id) => set({ reframeMode: id })}
          options={[{ id: 'auto', label: 'Auto' }, { id: 'subject', label: 'Subject' }, { id: 'disabled', label: 'Off' }]} /></div>
      </div>
      <OptRow icon="scissors" label="Smart cut" desc="Remove silence & filler words"
        on={opts.smartcut} set={(v) => set({ smartcut: v })} />
      <OptRow icon="zoom-in" label="Subtle zoom" desc="Gentle Ken Burns motion (1.0→1.05x)"
        on={opts.zoom} set={(v) => set({ zoom: v })} />
      <div className="opt">
        <div className="oico"><Icon n="languages" /></div>
        <div className="otxt" style={{ flex: 1 }}><div className="ot">Spoken language</div><div className="od">Single language boosts accuracy</div></div>
        <div className="r" style={{ flex: '0 0 184px' }}>
          <select className="sel" value={opts.language} onChange={(e) => set({ language: e.target.value })}>
            {LANGUAGES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </div>
      </div>

      <div className="label" style={{ margin: '16px 0 4px' }}>Captions &amp; hooks</div>
      <OptRow icon="captions" label="Subtitles" desc="Burn karaoke or classic captions"
        on={opts.subtitles} set={(v) => set({ subtitles: v })} onConfig={() => setSubCfg(!subCfg)} configActive={subCfg} />
      {opts.subtitles && subCfg && <SubConfig opts={opts} set={set} />}
      <OptRow icon="type" label="Text hooks" desc="Add a scroll-stopping opener"
        on={opts.hooks} set={(v) => set({ hooks: v })} onConfig={() => setHookCfg(!hookCfg)} configActive={hookCfg} />
      {opts.hooks && hookCfg && <HookConfig opts={opts} set={set} />}
      <OptRow icon="stamp" label="Brand logo" desc="Burn your logo onto every clip"
        on={opts.logo} set={(v) => set({ logo: v })} onConfig={() => setLogoCfg(!logoCfg)} configActive={logoCfg} />
      {opts.logo && logoCfg && <LogoConfig opts={opts} set={set} />}
      <OptRow icon="rss" label="Attribution banner" desc="Platform logo + handle burned bottom of clip"
        on={opts.banner} set={(v) => set({ banner: v })} onConfig={() => setBannerCfg(!bannerCfg)} configActive={bannerCfg} />
      {opts.banner && bannerCfg && <BannerConfig opts={opts} set={set} />}
      <div className="opt">
        <div className="oico"><Icon n="palette" /></div>
        <div className="otxt"><div className="ot">Colour grade</div><div className="od">Cinematic colour pass on every clip</div></div>
        <div className="r"><GradeControls withOff full={false} preset={opts.gradePreset || 'none'}
          onChange={(p) => set({ gradePreset: p.preset })} /></div>
      </div>
    </Panel>
  );
}

function SummaryBar({ opts, ready, count, onCreate, error }) {
  const chips = [
    opts.aspect || '9:16',
    opts.clipsAuto ? 'auto clips' : `~${opts.clips} clips`,
    opts.detect ? 'viral detect' : 'whole video',
    (() => { const m = opts.reframeMode || (opts.reframe === false ? 'disabled' : 'auto'); return (m === 'subject' || m === 'object') ? 'subject crop' : m === 'disabled' ? 'letterbox' : 'reframe'; })(),
    opts.smartcut && 'smart-cut',
    opts.subtitles && (opts.subMode + ' subs'),
    opts.hooks && 'hooks',
  ].filter(Boolean);
  return (
    <div className="summary">
      <div>
        <div className="s-main">{ready ? (opts.clipsAuto ? 'ClippyMe will pick the best clips' : `Aiming for about ${count} clip${count === 1 ? '' : 's'}`) : 'Add a source to get started'}</div>
        <div className="s-sub">
          {chips.map((c) => <span key={c} className="chip">{c}</span>)}
        </div>
        {error && <div className="field-error" role="alert">{error}</div>}
      </div>
      <div className="s-right">
        <Btn variant="grad" size="lg" icon="wand-sparkles" onClick={onCreate} disabled={!ready}>Create clips</Btn>
      </div>
    </div>
  );
}

export function CreateView({ opts, set, onPickPreset, onCreate, presets, defaultId, onSetDefault, onDelete, onSaveCurrent }) {
  const validation = validateCreateOptions(opts);
  const ready = validation.valid;
  const nSources = Math.max(1, validation.sourceCount);
  const count = opts.detect ? opts.clips * nSources : nSources;
  return (
    <div className="container fade-in">
      <Hero eyebrow="Drop a link · get scroll-stopping shorts" line1="Long videos in." grad="Viral shorts out."
        sub="Drop a link from YouTube, Twitch, or Kick (or upload a file) and ClippyMe does the rest: transcribes it, finds the best moments, reframes and trims them, and queues the top clips to post." />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
        {/* Order: pick a source first, then optionally start from a preset,
            then fine-tune the recipe by hand. */}
        <SourcePanel opts={opts} set={set} />
        <div>
          <div className="label" style={{ marginBottom: 12 }}>Start from a preset, or set everything by hand below</div>
          <PresetCards presets={presets} active={opts.preset} defaultId={defaultId}
            onPick={onPickPreset} onSetDefault={onSetDefault} onDelete={onDelete} onSaveCurrent={onSaveCurrent} />
        </div>
        <OptionsPanel opts={opts} set={set} />
      </div>
      <SummaryBar opts={opts} ready={ready} count={count} onCreate={onCreate} error={validation.firstError} />
    </div>
  );
}
