// ClippyMe — SettingsView + ApiKeyModal, wired to the real backend
// (config keys, cookies, Zernio).
import { useState, useEffect, useRef } from 'react';
import { Icon, Btn, Badge, Switch, Segmented, Panel } from '../../components/primitives';
import { Hero } from '../../components/headers';
import {
  getConfig, saveConfig, getModels, cookiesStatus, uploadCookies, deleteCookies,
  getZernio, saveZernio, discoverZernioAccounts,
  listFonts, uploadFont, deleteFont, logoStatus, uploadLogo, deleteLogo,
} from '../../api/client';
import { SUB_FONTS } from '../../lib/uiOptions';
import { getApiToken, setApiToken } from '../../api/apiToken';
import { getCredentialMode, setCredentialMode } from '../../lib/credentialStorage';

const LLM_PROVIDERS = [
  ['gemini', 'Google Gemini'], ['openai', 'OpenAI'], ['openrouter', 'OpenRouter'],
  ['anthropic', 'Claude (Anthropic)'], ['deepseek', 'DeepSeek'],
];
const LLM_KEY_NAMES = {
  gemini: 'GEMINI_API_KEY', openai: 'OPENAI_API_KEY', openrouter: 'OPENROUTER_API_KEY',
  anthropic: 'ANTHROPIC_API_KEY', deepseek: 'DEEPSEEK_API_KEY',
};

function KeyRow({ icon, name, desc, value, onChange, onSave, onClear, placeholder, present }) {
  const [reveal, setReveal] = useState(false);
  // Only persist (and toast) when the field actually changed during this focus
  // session — tabbing past an already-set key shouldn't spam saves/toasts.
  const focusVal = useRef(value);
  return (
    <div className="keyrow">
      <div className="ki"><Icon n={icon} /></div>
      <div style={{ minWidth: 0 }}>
        <div className="kt">{name}</div>
        <div className="kd">{desc}</div>
      </div>
      <div className="kr">
        <input className="key-input" type={reveal ? 'text' : 'password'} value={value}
          aria-label={name}
          placeholder={placeholder} onChange={(e) => onChange(e.target.value)}
          onFocus={() => { focusVal.current = value; }}
          onBlur={() => { if (value !== focusVal.current) onSave(); }} />
        <button type="button" className="mini" title={reveal ? 'Hide' : 'Show'} aria-label={reveal ? 'Hide key' : 'Show key'} onClick={() => setReveal(!reveal)}><Icon n={reveal ? 'eye-off' : 'eye'} /></button>
        {/* Backend-confirmed state only — raw input text (typed but not yet
            saved) must never flip this badge. */}
        {present ? <Badge tone="teal" icon="check">set</Badge> : <Badge tone="out">empty</Badge>}
        {present && onClear && (
          <button type="button" className="mini" title="Clear saved key" aria-label={`Clear ${name} key`} onClick={onClear}><Icon n="x" /></button>
        )}
      </div>
    </div>
  );
}

export function SettingsView({ apiKey, onApiKey, cookiesConfigured, onCookiesChange, pushToast }) {
  const [gemini, setGemini] = useState(apiKey || '');
  const [openai, setOpenai] = useState('');
  const [openrouter, setOpenrouter] = useState('');
  const [anthropic, setAnthropic] = useState('');
  const [deepseek, setDeepseek] = useState('');
  const [deepgram, setDeepgram] = useState('');
  const [elevenlabs, setElevenlabs] = useState('');
  const [hf, setHf] = useState('');
  const [twitchId, setTwitchId] = useState('');
  const [twitchSecret, setTwitchSecret] = useState('');
  const [apiToken, setApiTokenState] = useState(() => getApiToken());
  const [browserRetention, setBrowserRetention] = useState(() => getCredentialMode());
  const [present, setPresent] = useState({});
  const [zernio, setZernioState] = useState(null);
  const [zKey, setZKey] = useState('');
  const [accts, setAccts] = useState({ tiktok: '', instagram: '', youtube: '' });
  const [cookies, setCookies] = useState(!!cookiesConfigured);
  const [logoOn, setLogoOn] = useState(false);
  const [fonts, setFonts] = useState([]);
  const [provider, setProvider] = useState('deepgram');
  const [model, setModel] = useState('');
  const [models, setModels] = useState([]);
  const [loadingModels, setLoadingModels] = useState(false);
  const [modelsError, setModelsError] = useState('');
  const modelsRequestId = useRef(0);
  const [llmConfigLoaded, setLlmConfigLoaded] = useState(false);

  // Fetch the selected provider's live catalog through the local backend.
  // Provider credentials never leave the machine and the UI has no free-text
  // model input or stale hard-coded catalog.
  const loadModels = async (provider = 'gemini', forceRefresh = false, preferredModel = model) => {
    const requestId = ++modelsRequestId.current;
    setLoadingModels(true);
    setModelsError('');
    try {
      const result = await getModels(provider, { forceRefresh });
      if (requestId !== modelsRequestId.current) return;
      const live = Array.isArray(result?.models) ? result.models : [];
      setModels(live);
      setModelsError(result?.error || (!live.length ? 'No compatible models were returned for this API key.' : ''));
      if (live.length && !live.some((item) => item.name === preferredModel)) {
        const latest = live[0]?.name || '';
        setModel(latest);
        if (latest) await saveConfig({ LLM_MODEL: latest, ...(provider === 'gemini' ? { GEMINI_MODEL: latest } : {}) });
      } else if (preferredModel) setModel(preferredModel);
    } catch (error) {
      if (requestId === modelsRequestId.current) {
        setModels([]);
        setModelsError(error?.message || 'Could not load the provider model catalog.');
      }
    } finally {
      if (requestId === modelsRequestId.current) setLoadingModels(false);
    }
  };

  // Source of truth for "is this key set" is always the backend's response,
  // never the (optimistic) input text — refetched after every save/clear so
  // the badge can't drift from what's actually persisted.
  const refreshConfig = async () => {
    const c = await getConfig();
    if (!c) { pushToast?.('warn', 'Could not refresh key status'); return; }
    setPresent({
      gemini: !!c.GEMINI_API_KEY, hf: !!c.HF_TOKEN, deepgram: !!c.DEEPGRAM_API_KEY, elevenlabs: !!c.ELEVENLABS_API_KEY,
      openai: !!c.OPENAI_API_KEY, openrouter: !!c.OPENROUTER_API_KEY,
      anthropic: !!c.ANTHROPIC_API_KEY, deepseek: !!c.DEEPSEEK_API_KEY,
      twitchId: !!c.TWITCH_CLIENT_ID, twitchSecret: !!c.TWITCH_CLIENT_SECRET,
    });
    if (c.TRANSCRIPTION_PROVIDER) setProvider(c.TRANSCRIPTION_PROVIDER);
    if (c.LLM_PROVIDER) setLlmProvider(c.LLM_PROVIDER);
    const savedModel = c.LLM_MODEL || c.GEMINI_MODEL || '';
    setModel(savedModel);
    return c;
  };

  const [llmProvider, setLlmProvider] = useState('gemini');

  useEffect(() => {
    refreshConfig().then((c) => {
      setLlmConfigLoaded(true);
      return loadModels(c?.LLM_PROVIDER || 'gemini', false, c?.LLM_MODEL || c?.GEMINI_MODEL || '');
    }).catch(() => setLlmConfigLoaded(true));
    getZernio().then((z) => { setZernioState(z); if (z.accounts) setAccts({ tiktok: '', instagram: '', youtube: '', ...z.accounts }); }).catch(() => {});
    cookiesStatus().then((s) => setCookies(!!s.configured)).catch(() => {});
    logoStatus().then((s) => setLogoOn(!!s.configured)).catch(() => {});
    listFonts().then(({ fonts: f }) => setFonts(Array.isArray(f) ? f : [])).catch(() => {});
    // Mount-once bootstrap; loadModels reads the latest key via closure on call.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const saveKeys = async (patch) => {
    try {
      await saveConfig(patch);
      pushToast?.('success', 'Saved');
      await refreshConfig();
      const activeKey = LLM_KEY_NAMES[llmProvider];
      if (activeKey && Object.hasOwn(patch, activeKey)) await loadModels(llmProvider, true, model);
    }
    catch { pushToast?.('error', 'Save failed'); }
  };

  const selectLlmProvider = async (next) => {
    setLlmProvider(next);
    setModel('');
    setModels([]);
    setModelsError('');
    try {
      await saveConfig({ LLM_PROVIDER: next, LLM_MODEL: '' });
      await loadModels(next, true, '');
      pushToast?.('success', 'AI provider updated');
    } catch { pushToast?.('error', 'Could not update AI provider'); }
  };

  const selectLlmModel = (next) => {
    setModel(next);
    saveKeys({ LLM_MODEL: next, ...(llmProvider === 'gemini' ? { GEMINI_MODEL: next } : {}) });
  };

  const saveZernioCfg = async () => {
    try {
      const payload = { accounts: accts };
      if (zKey.trim()) payload.api_key = zKey.trim();
      const z = await saveZernio(payload);
      setZernioState(z); setZKey('');
      pushToast?.('success', 'Zernio saved');
    } catch { pushToast?.('error', 'Zernio save failed'); }
  };

  const discover = async () => {
    try {
      // Discovery runs against the *saved* key, so persist a freshly-typed one
      // first — otherwise the backend 400s with "API key not configured".
      if (zKey.trim()) { await saveZernio({ api_key: zKey.trim(), accounts: accts }); setZKey(''); }
      const { accounts } = await discoverZernioAccounts();
      const next = { ...accts };
      (accounts || []).forEach((a) => {
        const p = (a.platform || '').toLowerCase();
        const id = a._id || a.id;
        if (p.includes('tiktok')) next.tiktok = id;
        else if (p.includes('insta')) next.instagram = id;
        else if (p.includes('you')) next.youtube = id;
      });
      setAccts(next);
      pushToast?.('success', `Discovered ${(accounts || []).length} accounts`);
    } catch { pushToast?.('error', 'Discover failed. Check the API key.'); }
  };

  const onCookieFile = async (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    try { await uploadCookies(f); setCookies(true); onCookiesChange?.(true); pushToast?.('success', 'Cookies uploaded'); }
    catch { pushToast?.('error', 'Cookie upload failed'); }
  };
  const removeCookies = async () => {
    try { await deleteCookies(); setCookies(false); onCookiesChange?.(false); pushToast?.('info', 'Cookies removed'); }
    catch { pushToast?.('error', 'Remove failed'); }
  };

  const onLogoFile = async (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    try { await uploadLogo(f); setLogoOn(true); pushToast?.('success', 'Logo uploaded'); }
    catch (err) { pushToast?.('error', String(err.message || 'Logo upload failed').slice(0, 80)); }
  };
  const removeLogo = async () => {
    try { await deleteLogo(); setLogoOn(false); pushToast?.('info', 'Logo removed'); }
    catch { pushToast?.('error', 'Remove failed'); }
  };

  // Only user-uploaded faces are deletable; bundled ones are part of the app.
  const bundled = new Set(SUB_FONTS.map(([v]) => v));
  const onFontFile = async (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    try { const { fonts: nf } = await uploadFont(f); setFonts(nf || fonts); pushToast?.('success', 'Font added'); }
    catch (err) { pushToast?.('error', String(err.message || 'Font upload failed').slice(0, 80)); }
  };
  const removeFont = async (name) => {
    try { const { fonts: nf } = await deleteFont(name); setFonts(nf || fonts.filter((n) => n !== name)); pushToast?.('info', 'Font removed'); }
    catch { pushToast?.('error', 'Remove failed'); }
  };

  return (
    <div className="container narrow fade-in">
      <Hero eyebrow="Settings" line1="Keys & connections." sub="Everything is stored locally. Your keys never leave your machine." />

      <Panel title="API keys" sub="Required for transcription & moment detection" icon="key-round" style={{ marginBottom: 18 }}>
        <div className="opt" role="group" aria-label="Browser credential retention">
          <div className="oico"><Icon n="shield" /></div>
          <div className="otxt">
            <div className="ot">Browser credential retention</div>
            <div className="od">Session only clears browser copies when the browser session ends. Backend provider keys remain stored on the server.</div>
          </div>
          <div className="r">
            <select aria-label="Browser credential retention" className="key-input" value={browserRetention}
              onChange={(event) => { setBrowserRetention(setCredentialMode(event.target.value)); pushToast?.('info', 'Browser credential retention updated'); }}>
              <option value="local">Remember on this device</option>
              <option value="session">Session only (safer)</option>
            </select>
          </div>
        </div>
        <KeyRow icon="sparkles" name="Gemini" desc="Viral-moment detection" value={gemini} present={present.gemini}
          onChange={(v) => { setGemini(v); onApiKey?.(v); }} onSave={() => saveKeys({ GEMINI_API_KEY: gemini })}
          onClear={() => { setGemini(''); onApiKey?.(''); saveKeys({ GEMINI_API_KEY: '' }); }} placeholder="AIza…" />
        <KeyRow icon="sparkles" name="OpenAI" desc="LLM video-moment detection" value={openai} present={present.openai}
          onChange={setOpenai} onSave={() => saveKeys({ OPENAI_API_KEY: openai })}
          onClear={() => { setOpenai(''); saveKeys({ OPENAI_API_KEY: '' }); }} placeholder="sk-…" />
        <KeyRow icon="network" name="OpenRouter" desc="One key for models from multiple providers" value={openrouter} present={present.openrouter}
          onChange={setOpenrouter} onSave={() => saveKeys({ OPENROUTER_API_KEY: openrouter })}
          onClear={() => { setOpenrouter(''); saveKeys({ OPENROUTER_API_KEY: '' }); }} placeholder="sk-or-v1-…" />
        <KeyRow icon="sparkles" name="Claude (Anthropic)" desc="Claude model detection" value={anthropic} present={present.anthropic}
          onChange={setAnthropic} onSave={() => saveKeys({ ANTHROPIC_API_KEY: anthropic })}
          onClear={() => { setAnthropic(''); saveKeys({ ANTHROPIC_API_KEY: '' }); }} placeholder="sk-ant-…" />
        <KeyRow icon="sparkles" name="DeepSeek" desc="DeepSeek model detection" value={deepseek} present={present.deepseek}
          onChange={setDeepseek} onSave={() => saveKeys({ DEEPSEEK_API_KEY: deepseek })}
          onClear={() => { setDeepseek(''); saveKeys({ DEEPSEEK_API_KEY: '' }); }} placeholder="sk-…" />
        <KeyRow icon="audio-lines" name="Deepgram" desc="Nova-3 transcription" value={deepgram} present={present.deepgram}
          onChange={setDeepgram} onSave={() => saveKeys({ DEEPGRAM_API_KEY: deepgram })}
          onClear={() => { setDeepgram(''); saveKeys({ DEEPGRAM_API_KEY: '' }); }} placeholder="dg_…" />
        <KeyRow icon="audio-lines" name="ElevenLabs" desc="Scribe transcription · audio-event tags" value={elevenlabs} present={present.elevenlabs}
          onChange={setElevenlabs} onSave={() => saveKeys({ ELEVENLABS_API_KEY: elevenlabs })}
          onClear={() => { setElevenlabs(''); saveKeys({ ELEVENLABS_API_KEY: '' }); }} placeholder="sk_…" />
        <KeyRow icon="scan-face" name="Hugging Face token" desc="Speaker diarization models" value={hf} present={present.hf}
          onChange={setHf} onSave={() => saveKeys({ HF_TOKEN: hf })}
          onClear={() => { setHf(''); saveKeys({ HF_TOKEN: '' }); }} placeholder="hf_…" />
        <KeyRow icon="rss" name="Twitch client ID" desc="Live Monitor: Twitch channel detection" value={twitchId} present={present.twitchId}
          onChange={setTwitchId} onSave={() => saveKeys({ TWITCH_CLIENT_ID: twitchId })}
          onClear={() => { setTwitchId(''); saveKeys({ TWITCH_CLIENT_ID: '' }); }} placeholder="Helix app client id" />
        <KeyRow icon="rss" name="Twitch client secret" desc="Live Monitor: Twitch channel detection" value={twitchSecret} present={present.twitchSecret}
          onChange={setTwitchSecret} onSave={() => saveKeys({ TWITCH_CLIENT_SECRET: twitchSecret })}
          onClear={() => { setTwitchSecret(''); saveKeys({ TWITCH_CLIENT_SECRET: '' }); }} placeholder="Helix app client secret" />
        <KeyRow icon="key-round" name="API token" desc="Only for LAN deploys with CLIPPYME_API_TOKEN set — stored in this browser, sent as X-API-Token" value={apiToken} present={!!getApiToken()}
          onChange={setApiTokenState} onSave={() => { setApiToken(apiToken); pushToast?.('success', apiToken.trim() ? 'API token saved' : 'API token cleared'); }} placeholder="Shared secret (leave empty + Save to clear)" />
        <div className="opt" style={{ borderBottom: 0 }}>
          <div className="oico"><Icon n="audio-lines" /></div>
          <div className="otxt"><div className="ot">Transcription engine</div><div className="od">Cloud STT falls back to local Whisper if its key is missing</div></div>
          <div className="r"><Segmented value={provider}
            onChange={(id) => { setProvider(id); saveKeys({ TRANSCRIPTION_PROVIDER: id }); }}
            options={[{ id: 'deepgram', label: 'Deepgram' }, { id: 'elevenlabs', label: 'ElevenLabs' }, { id: 'whisper', label: 'Whisper' }]} /></div>
        </div>
        {provider === 'deepgram' && !present.deepgram && (
          <div className="od" style={{ color: 'var(--warn, #f5a623)', padding: '0 0 8px 44px' }}>⚠ No Deepgram key saved — pipeline will use local Whisper.</div>
        )}
        {provider === 'elevenlabs' && !present.elevenlabs && (
          <div className="od" style={{ color: 'var(--warn, #f5a623)', padding: '0 0 8px 44px' }}>⚠ No ElevenLabs key saved — pipeline will use local Whisper.</div>
        )}
        <div className="opt">
          <div className="oico"><Icon n="sparkles" /></div>
          <div className="otxt"><div className="ot">Analysis provider</div><div className="od">Choose the API used to find viral moments · applied to new jobs</div></div>
          <div className="r">
            <select aria-label="Analysis provider" className="key-input" value={llmProvider}
              onChange={(e) => selectLlmProvider(e.target.value)} disabled={!llmConfigLoaded}>
              {LLM_PROVIDERS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </div>
        </div>
        <div className="opt" style={{ borderBottom: 0 }}>
          <div className="oico"><Icon n="sparkles" /></div>
          <div className="otxt"><div className="ot">Available models</div><div className="od">Loaded from the selected provider&apos;s live API catalog</div>
            {modelsError && <div className="od" role="status" style={{ color: 'var(--warn, #f5a623)' }}>{modelsError}</div>}
          </div>
          <div className="r" style={{ gap: 8 }}>
            <select aria-label="Analysis model" className="key-input" style={{ width: 'auto', minWidth: 200, fontFamily: 'var(--font-sans)' }}
              value={model} onChange={(e) => selectLlmModel(e.target.value)} disabled={loadingModels || !models.length}>
              {!model && <option value="">{loadingModels ? 'Loading models…' : 'Add a provider API key'}</option>}
              {model && !models.some((m) => m.name === model) && <option value={model}>{model} · saved selection</option>}
              {models.map((m) => <option key={m.name} value={m.name}>{m.display_name || m.name}</option>)}
            </select>
            <Btn variant="ghost" size="sm" icon="refresh-cw" onClick={() => loadModels(llmProvider, true)} disabled={loadingModels}>
              {loadingModels ? '…' : 'Refresh'}
            </Btn>
          </div>
        </div>
      </Panel>

      <Panel title="Publishing" sub="Push finished clips to socials via Zernio" icon="send" style={{ marginBottom: 18 }}>
        <div className="zernio-card" style={{ flexDirection: 'column', alignItems: 'stretch', gap: 14 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
            <div className="zico"><Icon n="rss" /></div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="kt">Zernio</div>
              <div className="kd">{zernio?.configured ? `Connected${zernio.api_key_masked ? ' · ' + zernio.api_key_masked : ''}` : 'Add your API key + account IDs to schedule posts'}</div>
            </div>
            {zernio?.configured && <span className="conn"><Icon n="circle-check" />Connected</span>}
          </div>
          <input className="key-input" style={{ width: '100%' }} type="password" value={zKey}
            aria-label="Zernio API key"
            placeholder={zernio?.configured ? 'Replace API key (optional)' : 'Zernio API key (sk_…)'} onChange={(e) => setZKey(e.target.value)} />
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 8 }}>
            {['tiktok', 'instagram', 'youtube'].map((p) => (
              <input key={p} className="key-input" style={{ width: '100%', fontFamily: 'var(--font-sans)' }}
                aria-label={`${p} account id`}
                value={accts[p] || ''} placeholder={`${p} account id`} onChange={(e) => setAccts((a) => ({ ...a, [p]: e.target.value }))} />
            ))}
          </div>
          <div style={{ display: 'flex', gap: 10 }}>
            <Btn variant="secondary" size="sm" icon="rss" onClick={discover}>Discover from Zernio</Btn>
            <Btn variant="primary" size="sm" icon="check" onClick={saveZernioCfg}>Save</Btn>
          </div>
        </div>
      </Panel>

      <Panel title="Brand assets" sub="Logo overlay + custom subtitle fonts" icon="stamp" style={{ marginBottom: 18 }}>
        <div className="opt">
          <div className="oico"><Icon n="image" /></div>
          <div className="otxt"><div className="ot">Brand logo</div><div className="od">{logoOn ? 'Configured · burned on clips when the Logo layer is on' : 'Upload a transparent PNG to overlay on clips'}</div></div>
          <div className="r" style={{ gap: 8 }}>
            <label className="btn btn-secondary btn-sm" style={{ cursor: 'pointer' }}>
              <Icon n="upload" />Upload
              <input type="file" accept="image/png,.png" hidden onChange={onLogoFile} />
            </label>
            {logoOn && <Btn variant="ghost" size="sm" icon="trash-2" onClick={removeLogo}>Remove</Btn>}
          </div>
        </div>
        <div className="opt" style={{ borderBottom: 0, alignItems: 'flex-start' }}>
          <div className="oico"><Icon n="baseline" /></div>
          <div className="otxt" style={{ flex: 1 }}>
            <div className="ot">Subtitle fonts</div>
            <div className="od">Upload a .ttf/.otf (e.g. Stratos) to use in classic captions</div>
            {fonts.filter((n) => !bundled.has(n)).length > 0 && (
              <div className="s-sub" style={{ marginTop: 10 }}>
                {fonts.filter((n) => !bundled.has(n)).map((n) => (
                  <span key={n} className="chip" style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                    {n}
                    <button type="button" className="mini" aria-label={`Remove ${n}`} title="Remove" onClick={() => removeFont(n)}><Icon n="x" /></button>
                  </span>
                ))}
              </div>
            )}
          </div>
          <div className="r">
            <label className="btn btn-secondary btn-sm" style={{ cursor: 'pointer' }}>
              <Icon n="upload" />Upload
              <input type="file" accept=".ttf,.otf,.ttc,font/ttf,font/otf" hidden onChange={onFontFile} />
            </label>
          </div>
        </div>
      </Panel>

      <Panel title="Downloads" sub="For age- or region-restricted sources" icon="cookie">
        <div className="opt" style={{ borderBottom: 0 }}>
          <div className="oico"><Icon n="cookie" /></div>
          <div className="otxt"><div className="ot">YouTube cookies</div><div className="od">{cookies ? 'Configured · restricted videos OK' : 'Not set · public videos only'}</div></div>
          <div className="r" style={{ gap: 8 }}>
            <label className="btn btn-secondary btn-sm" style={{ cursor: 'pointer' }}>
              <Icon n="upload" />Upload
              <input type="file" accept=".txt" hidden onChange={onCookieFile} />
            </label>
            {cookies && <Btn variant="ghost" size="sm" icon="trash-2" onClick={removeCookies}>Remove</Btn>}
          </div>
        </div>
      </Panel>
    </div>
  );
}
