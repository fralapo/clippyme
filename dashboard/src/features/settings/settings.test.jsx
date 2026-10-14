// SettingsView key-status badges — pins the bug fix where the "set"/"empty"
// badge must reflect backend-confirmed `present` state, never the raw input
// text, and must refresh after save/clear instead of going stale or being
// wiped by a transient getConfig failure.
import { test, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, within, waitFor } from '@testing-library/react';
import { SettingsView } from './settings.jsx';
import { getModels } from '../../api/client';

const getConfig = vi.fn();
const saveConfig = vi.fn();

vi.mock('../../api/client', () => ({
  getConfig: (...a) => getConfig(...a),
  saveConfig: (...a) => saveConfig(...a),
  getModels: vi.fn(async () => ({ models: [] })),
  cookiesStatus: vi.fn(async () => ({ configured: false })),
  uploadCookies: vi.fn(),
  deleteCookies: vi.fn(),
  getZernio: vi.fn(async () => ({ configured: false })),
  saveZernio: vi.fn(),
  discoverZernioAccounts: vi.fn(),
  listFonts: vi.fn(async () => ({ fonts: [] })),
  uploadFont: vi.fn(),
  deleteFont: vi.fn(),
  logoStatus: vi.fn(async () => ({ configured: false })),
  uploadLogo: vi.fn(),
  deleteLogo: vi.fn(),
}));

const EMPTY_CONFIG = { GEMINI_API_KEY: '', HF_TOKEN: '', DEEPGRAM_API_KEY: '', ELEVENLABS_API_KEY: '' };
const SET_CONFIG = { ...EMPTY_CONFIG, GEMINI_API_KEY: 'AIza...xyz1' };

beforeEach(() => {
  vi.clearAllMocks();
  saveConfig.mockResolvedValue({ success: true });
});

function mount(pushToast = vi.fn()) {
  render(<SettingsView pushToast={pushToast} />);
  return pushToast;
}

const geminiRow = () => screen.getByLabelText('Gemini').closest('.keyrow');

test('badge reflects backend state, not input text typed before any save', async () => {
  getConfig.mockResolvedValue(EMPTY_CONFIG);
  mount();
  await waitFor(() => expect(within(geminiRow()).getByText('empty')).toBeInTheDocument());

  // Typing into the field (no blur/save yet) must not flip the badge.
  fireEvent.change(screen.getByLabelText('Gemini'), { target: { value: 'AIzaSomeKey' } });
  expect(within(geminiRow()).getByText('empty')).toBeInTheDocument();
  expect(within(geminiRow()).queryByText('set')).toBeNull();
});

test('save triggers a refetch and the badge updates from the backend response', async () => {
  getConfig.mockResolvedValueOnce(EMPTY_CONFIG).mockResolvedValueOnce(SET_CONFIG);
  mount();
  await waitFor(() => expect(within(geminiRow()).getByText('empty')).toBeInTheDocument());

  const input = screen.getByLabelText('Gemini');
  fireEvent.focus(input);
  fireEvent.change(input, { target: { value: 'AIzaSomeKey' } });
  fireEvent.blur(input);

  expect(saveConfig).toHaveBeenCalledWith({ GEMINI_API_KEY: 'AIzaSomeKey' });
  await waitFor(() => expect(getConfig).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(within(geminiRow()).getByText('set')).toBeInTheDocument());
});

test('a failed post-save refetch does not wipe previously-known present state', async () => {
  getConfig.mockResolvedValueOnce(SET_CONFIG).mockResolvedValueOnce(null);
  const pushToast = mount();
  await waitFor(() => expect(within(geminiRow()).getByText('set')).toBeInTheDocument());

  const input = screen.getByLabelText('Deepgram');
  fireEvent.focus(input);
  fireEvent.change(input, { target: { value: 'dg_key' } });
  fireEvent.blur(input);

  await waitFor(() => expect(getConfig).toHaveBeenCalledTimes(2));
  // Gemini's badge (unrelated to the Deepgram save) must still read "set".
  expect(within(geminiRow()).getByText('set')).toBeInTheDocument();
  expect(pushToast).toHaveBeenCalledWith('warn', expect.any(String));
});

test('clearing a present key saves an empty value and the badge flips to empty', async () => {
  getConfig.mockResolvedValueOnce(SET_CONFIG).mockResolvedValueOnce(EMPTY_CONFIG);
  mount();
  await waitFor(() => expect(within(geminiRow()).getByText('set')).toBeInTheDocument());

  fireEvent.click(within(geminiRow()).getByRole('button', { name: 'Clear Gemini key' }));

  expect(saveConfig).toHaveBeenCalledWith({ GEMINI_API_KEY: '' });
  await waitFor(() => expect(within(geminiRow()).getByText('empty')).toBeInTheDocument());
});

test('Twitch client id/secret rows reflect backend present state', async () => {
  getConfig.mockResolvedValue({ ...EMPTY_CONFIG, TWITCH_CLIENT_ID: 'abcd1234', TWITCH_CLIENT_SECRET: 'shhh12345678' });
  mount();
  const idRow = () => screen.getByLabelText('Twitch client ID').closest('.keyrow');
  const secretRow = () => screen.getByLabelText('Twitch client secret').closest('.keyrow');
  await waitFor(() => expect(within(idRow()).getByText('set')).toBeInTheDocument());
  expect(within(secretRow()).getByText('set')).toBeInTheDocument();
});

test('Twitch client id/secret rows show empty when unset', async () => {
  getConfig.mockResolvedValue(EMPTY_CONFIG);
  mount();
  const idRow = () => screen.getByLabelText('Twitch client ID').closest('.keyrow');
  await waitFor(() => expect(within(idRow()).getByText('empty')).toBeInTheDocument());
});

test('model picker is populated from the selected provider live catalog', async () => {
  getConfig.mockResolvedValue({ ...EMPTY_CONFIG, LLM_PROVIDER: 'openai', LLM_MODEL: 'gpt-5.1-mini', OPENAI_API_KEY: 'sk-...key' });
  getModels.mockResolvedValue({ models: [
    { name: 'gpt-5.1', display_name: 'GPT 5.1' },
    { name: 'gpt-5.1-mini', display_name: 'GPT 5.1 mini' },
  ] });
  mount();

  expect(await screen.findByRole('option', { name: 'GPT 5.1' })).toBeInTheDocument();
  expect(screen.getByLabelText('Analysis model')).toHaveValue('gpt-5.1-mini');
  expect(getModels).toHaveBeenCalledWith('openai', { forceRefresh: false });
  expect(saveConfig).not.toHaveBeenCalled();
  expect(screen.queryByRole('textbox', { name: 'Analysis model' })).toBeNull();
});

test('changing provider loads its catalog and never asks for a model ID as text', async () => {
  getConfig.mockResolvedValue({ ...EMPTY_CONFIG, LLM_PROVIDER: 'gemini', LLM_MODEL: 'gemini-3.5-flash' });
  getModels.mockImplementation(async (provider) => ({ models: [
    { name: `${provider}-live-model`, display_name: `${provider} live model` },
  ] }));
  mount();

  const providerSelect = screen.getByLabelText('Analysis provider');
  await waitFor(() => expect(providerSelect).toBeEnabled());
  fireEvent.change(providerSelect, { target: { value: 'deepseek' } });

  expect(await screen.findByRole('option', { name: 'deepseek live model' })).toBeInTheDocument();
  expect(getModels).toHaveBeenCalledWith('deepseek', { forceRefresh: true });
  expect(screen.getByLabelText('Analysis model')).toHaveValue('deepseek-live-model');
  expect(saveConfig).toHaveBeenCalledWith({ LLM_PROVIDER: 'deepseek', LLM_MODEL: '' });
  expect(saveConfig).toHaveBeenCalledWith({ LLM_MODEL: 'deepseek-live-model' });
  expect(screen.queryByRole('textbox', { name: 'Analysis model' })).toBeNull();
});
