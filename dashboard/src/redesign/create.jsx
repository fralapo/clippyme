// ClippyMe redesign — Create flow: presets + source + calm options recipe.
import { useState, useRef } from 'react';
import { Icon, Social, Btn, Panel, Segmented, Switch, Stepper, PlatPill, PLATFORMS } from './primitives';
import { Hero } from './chrome';
import { PRESETS, ASPECTS, SUBTITLE_PRESETS, LANGUAGES } from './data';

function PresetCards({ active, onPick }) {
  return (
    <div className="preset-row">
      {PRESETS.map((p) => (
        <button key={p.id} type="button" className={'preset' + (active === p.id ? ' on' : '')} onClick={() => onPick(p)}>
          <span className="pcheck"><Icon n="check" /></span>
          <span className="pico"><Icon n={p.icon} /></span>
          <span className="pt">{p.title}</span>
          <span className="pd">{p.desc}</span>
        </button>
      ))}
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
              <Social n="youtube" color="7E7E8F" size={19} />
              <input value={opts.url} placeholder="Paste a YouTube or video URL…"
                onChange={(e) => set({ url: e.target.value })} />
              <button type="button" className="paste" onClick={() => set({ url: 'https://youtube.com/watch?v=dQw4w9WgXcQ' })}>
                <Icon n="clipboard" />Paste
              </button>
            </div>
          ) : (
            <div className={'dropzone' + (opts.file ? ' has' : drag ? ' drag' : '')}
              onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
              onDragLeave={() => setDrag(false)}
              onDrop={(e) => { e.preventDefault(); setDrag(false); pickFile(e.dataTransfer.files?.[0]); }}
              onClick={() => { if (opts.file) { set({ file: null, fileName: '' }); } else { fileInput.current?.click(); } }}>
              <input ref={fileInput} type="file" accept="video/*,.mp4,.mov,.webm,.mkv,.m4v,.avi" hidden
                onChange={(e) => pickFile(e.target.files?.[0])} />
              <div className="dz-ico"><Icon n={opts.file ? 'file-video' : 'upload'} /></div>
              {opts.file ? (
                <div><b>{opts.fileName}</b><div className="label" style={{ marginTop: 6 }}>Ready · click to remove</div></div>
              ) : (
                <div>Drop a video or <b style={{ color: 'var(--brand-blue)' }}>browse</b>
                  <div className="label" style={{ marginTop: 6, textTransform: 'none', letterSpacing: 0 }}>MP4 · MOV · WEBM · up to 2&nbsp;GB</div></div>
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
            <div className="dropzone" style={{ padding: 18 }} onClick={() => batchInput.current?.click()}>
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
              <span className="chip" style={{ cursor: 'pointer', color: 'var(--danger)' }} onClick={() => set({ batchFiles: [] })}>clear files</span>
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

function SubConfig({ opts, set }) {
  return (
    <div className="cfg-drawer fade-in">
      <div className="cf-row">
        <span className="field-label" style={{ marginBottom: 9, display: 'flex' }}>Mode</span>
        <Segmented full value={opts.subMode} onChange={(id) => set({ subMode: id })}
          options={[{ id: 'karaoke', label: 'Karaoke' }, { id: 'classic', label: 'Classic' }]} />
      </div>
      {opts.subMode === 'karaoke' && (
        <div className="cf-row">
          <span className="field-label" style={{ marginBottom: 9, display: 'flex' }}>Style preset</span>
          <div className="subgrid">
            {SUBTITLE_PRESETS.map((p) => (
              <button key={p.id} type="button" className={'subpre' + (opts.subPreset === p.id ? ' on' : '')} onClick={() => set({ subPreset: p.id })}>
                <div className="prev"><span style={p.style}>WORD <span style={{ color: p.hi }}>UP</span></span></div>
                <div className="nm">{p.label}</div>
              </button>
            ))}
          </div>
        </div>
      )}
      <div className="cf-row">
        <span className="field-label" style={{ marginBottom: 9, display: 'flex' }}>Position</span>
        <Segmented full value={opts.subPosition} onChange={(id) => set({ subPosition: id })}
          options={[{ id: 'top', label: 'Top' }, { id: 'center', label: 'Center' }, { id: 'bottom', label: 'Bottom' }]} />
      </div>
    </div>
  );
}

function HookConfig({ opts, set }) {
  return (
    <div className="cfg-drawer fade-in">
      <div className="cf-row">
        <span className="field-label" style={{ marginBottom: 9, display: 'flex' }}>Position</span>
        <Segmented full value={opts.hookPos} onChange={(id) => set({ hookPos: id })}
          options={[{ id: 'top', label: 'Top' }, { id: 'center', label: 'Center' }, { id: 'bottom', label: 'Bottom' }]} />
      </div>
      <div className="cf-row">
        <span className="field-label" style={{ marginBottom: 9, display: 'flex' }}>Size</span>
        <Segmented full value={opts.hookSize} onChange={(id) => set({ hookSize: id })}
          options={[{ id: 'S', label: 'Small' }, { id: 'M', label: 'Medium' }, { id: 'L', label: 'Large' }]} />
      </div>
    </div>
  );
}

function OptionsPanel({ opts, set }) {
  const [subCfg, setSubCfg] = useState(false);
  const [hookCfg, setHookCfg] = useState(false);
  const togglePlat = (k) => set({ platforms: { ...opts.platforms, [k]: !opts.platforms[k] } });
  return (
    <Panel title="Recipe" sub="What ClippyMe makes from each video" icon="sliders-horizontal">
      <div className="label" style={{ marginBottom: 4 }}>Output</div>
      <div className="opt">
        <div className="oico"><Icon n="scissors" /></div>
        <div className="otxt"><div className="ot">Clips per video</div><div className="od">How many shorts to cut</div></div>
        <div className="r"><Stepper value={opts.clips} set={(v) => set({ clips: v })} /></div>
      </div>
      <div className="opt">
        <div className="oico"><Icon n="crop" /></div>
        <div className="otxt"><div className="ot">Aspect ratio</div><div className="od">Output frame</div></div>
        <div className="r"><Segmented value={opts.aspect} onChange={(id) => set({ aspect: id })}
          options={ASPECTS.map(([a]) => ({ id: a, label: a }))} /></div>
      </div>

      <div className="label" style={{ margin: '16px 0 4px' }}>AI &amp; reframe</div>
      <OptRow icon="sparkles" label="Find viral moments" desc="Gemini scores the transcript · off = whole video"
        on={opts.detect} set={(v) => set({ detect: v })} />
      <OptRow icon="scan-face" label="Auto reframe" desc="Face-tracking crop to 9:16 · off = letterbox"
        on={opts.reframe} set={(v) => set({ reframe: v })} />
      <OptRow icon="scissors" label="Smart cut" desc="Remove silence & filler words"
        on={opts.smartcut} set={(v) => set({ smartcut: v })} />
      <OptRow icon="zoom-in" label="Subtle zoom" desc="Gentle Ken Burns motion (1.0→1.05x)"
        on={opts.zoom} set={(v) => set({ zoom: v })} />
      <div className="opt">
        <div className="oico"><Icon n="languages" /></div>
        <div className="otxt" style={{ flex: 1 }}><div className="ot">Spoken language</div><div className="od">Single language boosts accuracy</div></div>
        <div className="r" style={{ flex: '0 0 150px' }}>
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

      <div className="label" style={{ margin: '16px 0 10px' }}>Publish to · via Zernio</div>
      <div className="plats">
        {PLATFORMS.map((p) => <PlatPill key={p.id} {...p} on={opts.platforms[p.id]} onClick={() => togglePlat(p.id)} />)}
      </div>
    </Panel>
  );
}

function SummaryBar({ opts, ready, count, onCreate }) {
  const chips = [
    opts.aspect,
    opts.detect ? 'viral detect' : 'whole video',
    opts.reframe && 'reframe',
    opts.smartcut && 'smart-cut',
    opts.subtitles && (opts.subMode + ' subs'),
    opts.hooks && 'hooks',
  ].filter(Boolean);
  const plats = Object.entries(opts.platforms).filter(([, v]) => v).map(([k]) => ({ tiktok: 'TikTok', ig: 'Reels', yt: 'Shorts' }[k]));
  return (
    <div className="summary">
      <div>
        <div className="s-main">{ready ? `ClippyMe will create ~${count} clip${count === 1 ? '' : 's'}` : 'Add a source to get started'}</div>
        <div className="s-sub">
          {chips.map((c) => <span key={c} className="chip">{c}</span>)}
          {plats.length > 0 && <span className="chip" style={{ borderColor: 'rgba(10,129,217,.4)', color: 'var(--blue-300)' }}>→ {plats.join(' · ')}</span>}
        </div>
      </div>
      <div className="s-right">
        <Btn variant="grad" size="lg" icon="wand-sparkles" onClick={onCreate} disabled={!ready}>Create clips</Btn>
      </div>
    </div>
  );
}

export function CreateView({ opts, set, onPickPreset, onCreate }) {
  const batchCount = opts.batch.split('\n').filter((l) => l.trim()).length + (opts.batchFiles || []).length;
  const ready = opts.mode === 'single'
    ? (opts.source === 'url' ? !!opts.url : !!opts.file)
    : batchCount > 0;
  const nSources = opts.mode === 'single' ? 1 : Math.max(1, batchCount);
  const count = opts.detect ? opts.clips * nSources : nSources;
  return (
    <div className="container fade-in">
      <Hero eyebrow="Drop a link · get scroll-stopping shorts" line1="Long videos in." grad="Viral shorts out."
        sub="Paste a YouTube link and ClippyMe transcribes, scores every moment, reframes to 9:16, trims the silence, and schedules the best cuts — automatically." />
      <div className="label" style={{ marginBottom: 12 }}>Start from a recipe</div>
      <PresetCards active={opts.preset} onPick={onPickPreset} />
      <div className="create-grid">
        <SourcePanel opts={opts} set={set} />
        <OptionsPanel opts={opts} set={set} />
      </div>
      <SummaryBar opts={opts} ready={ready} count={count} onCreate={onCreate} />
    </div>
  );
}
