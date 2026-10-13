// Real Chromium exercises React navigation and user events. HTTP responses are
// deterministic route fixtures: never touches AI providers or publishes posts.
import { test, expect } from '@playwright/test';

const JOB = '12345678-1234-4123-8123-1234567890ab';
const clip = {
  original_index: 0, video_title_for_youtube_short: 'A viral moment',
  tiktok_caption: 'An engaging clip', viral_score: 88, start: 0, end: 25,
  video_url: `/videos/${JOB}/clip_1.mp4`, reframe_mode: 'auto',
};
const job = {
  jobId: JOB, status: 'complete', clipCount: 1, publishedCount: 0,
  title: 'Test video', source: 'Test video', sourceType: 'url', timestamp: Date.now(),
};
const reply = (route, data, status = 200) => route.fulfill({
  status, contentType: 'application/json', body: JSON.stringify(data),
});

async function fixtures(page) {
  let polled = 0;
  let publications = 0;
  await page.addInitScript(() => {
    localStorage.clear();
    localStorage.setItem('gemini_key', 'browser-e2e-test-key');
    localStorage.setItem('clippyme_api_token', '');
  });
  await page.route(/^https?:\/\/[^/]+\/api\//, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (path === '/api/process') return reply(route, { job_id: JOB });
    if (path === `/api/status/${JOB}`) {
      polled++;
      return reply(route, polled > 1 ? {
        status: 'completed', logs: ['Finished'], result: { clips: [clip] },
      } : { status: 'processing', logs: ['Preparing pipeline'] });
    }
    if (path === '/api/history') return reply(route, { jobs: [job] });
    if (path === `/api/history/${JOB}/restore`) return reply(route, { result: { clips: [clip] } });
    if (path === '/api/config/zernio') return reply(route, {
      configured: true, timezone: 'Europe/Rome',
      accounts: { tiktok: 'test-account' },
    });
    if (path === `/api/publish/${JOB}/0`) {
      publications++;
      return reply(route, { success: true, status: 'submitted', post_id: 'fake-post-id' });
    }
    if (path === '/api/config') return reply(route, {});
    if (path === '/api/config/cookies/status') return reply(route, { configured: false });
    return reply(route, {}, 200);
  });
  await page.route('**/videos/**', (route) => route.fulfill({
    status: 404, contentType: 'text/plain', body: '',
  }));
  return { publications: () => publications };
}

test('Create → Processing → Results → Edit → Publish (browser interactions)', async ({ page }) => {
  const api = await fixtures(page);
  await page.goto('/');
  await page.getByPlaceholder(/Paste a video link/).fill('https://www.youtube.com/watch?v=dQw4w9WgXcQ');
  await page.getByRole('button', { name: 'Create clips' }).click();
  await expect(page.getByRole('list', { name: 'Generated clips' })).toBeVisible({ timeout: 30000 });
  await page.getByRole('button', { name: /Edit and reprocess A viral moment/ }).click();
  const modal = page.getByRole('dialog', { name: /Edit clip/ });
  await expect(modal).toBeVisible();
  await modal.getByRole('button', { name: 'Cancel' }).click();
  await page.getByRole('button', { name: 'Publish A viral moment' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Publish now' }).click();
  await expect(page.getByText('Clip submitted')).toBeVisible();
  expect(api.publications()).toBe(1);
});

test('History → Restore reopens disk-backed clips in a clean browser', async ({ page }) => {
  await fixtures(page);
  await page.goto('/');
  await page.getByRole('navigation', { name: 'Primary navigation' })
    .getByRole('button', { name: 'History' }).click();
  await expect(page.getByRole('button', { name: 'Open job Test video' })).toBeVisible();
  await page.getByRole('button', { name: 'Open job Test video' }).click();
  await expect(page.getByRole('list', { name: 'Generated clips' })).toBeVisible();
  await page.getByRole('button', { name: 'Back to history' }).click();
  await expect(page.getByRole('button', { name: 'Open job Test video' })).toBeVisible();
});
