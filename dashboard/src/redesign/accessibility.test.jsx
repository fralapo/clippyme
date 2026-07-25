import { cleanup, render } from '@testing-library/react'
import axe from 'axe-core'
import { afterEach, expect, test, vi } from 'vitest'
import { TopNav, Hero } from './chrome'
import { ProcessingView } from './processing'
import { Btn, Panel, Segmented, Stepper, Switch } from './primitives'
import { ResultsView } from './results'

const axeOptions = {
  rules: {
    // JSDOM does not calculate layout or painted colors reliably.
    'color-contrast': { enabled: false },
  },
}

async function expectAccessible(container) {
  const result = await axe.run(container, axeOptions)
  expect(result.violations.map(({ id, nodes }) => ({ id, nodes: nodes.map((node) => node.target) }))).toEqual([])
}

afterEach(() => cleanup())

test('shared navigation and controls expose an accessible DOM', async () => {
  const setTab = vi.fn()
  const { container } = render(
    <>
      <TopNav tab="create" setTab={setTab} busy={false} />
      <main>
        <Hero eyebrow="Create" line1="Turn video into clips" sub="Accessible controls" />
        <Panel title="Options" sub="Configure the job">
          <Btn icon="wand-sparkles">Create clips</Btn>
          <Switch on={false} onChange={vi.fn()} label="Enable subtitles" />
          <Segmented
            label="Aspect ratio"
            value="vertical"
            onChange={vi.fn()}
            options={[{ id: 'vertical', label: 'Vertical' }, { id: 'square', label: 'Square' }]}
          />
          <Stepper value={3} set={vi.fn()} label="Clip count" />
        </Panel>
      </main>
    </>,
  )
  await expectAccessible(container)
})

test('processing and empty results states pass the rendered accessibility gate', async () => {
  const processing = render(
    <ProcessingView
      media={{ type: 'url', payload: 'https://youtu.be/example' }}
      status="processing"
      logs={['queued', 'transcribing']}
      step="transcribing"
      clips={[]}
      onCancel={vi.fn()}
      opts={{ aspect: '9:16' }}
    />,
  )
  await expectAccessible(processing.container)
  processing.unmount()

  const results = render(
    <ResultsView
      clips={[]}
      jobId="job-1"
      preselections={{}}
      clipStates={{}}
      onUpdateClipState={vi.fn()}
      onBack={vi.fn()}
      onPublish={vi.fn()}
      onPublishAll={vi.fn()}
      onEdit={vi.fn()}
      onApplyToAll={vi.fn()}
      onEditSelected={vi.fn()}
    />,
  )
  await expectAccessible(results.container)
})
