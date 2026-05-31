/**
 * frontend/src/store/__tests__/report.test.ts
 *
 * Vitest unit tests for the v0.9.x report store. Exercises:
 *  - SSE message extraction (data.summary preferred, fallback to PROGRESS_LABELS,
 *    last-resort to event type).
 *  - startStreaming → ReadableStream parsing → state mutations
 *    (progress[], partialSections.report_markdown, fetchDetail on done).
 *
 * Implementation detail: `extractMessage` is a module-internal helper. We
 * verify its behavior indirectly via the public `startStreaming` action by
 * checking `reportState.streaming.progress[i].message` after we feed shaped
 * SSE events through a mocked fetch + ReadableStream.
 *
 * Lifecycle: the v0.9.x store moved to a *global* SSE subscription
 * (startStreaming returns void, cleanup via reportActions.cancelStreaming()).
 * Tests call cancelStreaming + resetStreaming in beforeEach to keep state
 * isolated across cases.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as reportsApi from '@/api/reports'
import { reportActions, reportState } from '@/store/report'

// ── helpers ────────────────────────────────────────────────────────────────

/**
 * Build a ReadableStream that emits the given SSE events as `data: <json>\n\n`
 * frames, then closes. Each event becomes one frame so the splitter sees the
 * full sequence in order.
 */
function makeSseStream(events: Array<{ type: string; data: unknown }>) {
  const encoder = new TextEncoder()
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const e of events) {
        const frame = `data: ${JSON.stringify(e)}\n\n`
        controller.enqueue(encoder.encode(frame))
      }
      controller.close()
    },
  })
}

/** Wait until predicate is true or timeout — used to await async store flush. */
async function waitFor(predicate: () => boolean, timeoutMs = 1000) {
  const start = Date.now()
  while (!predicate()) {
    if (Date.now() - start > timeoutMs) {
      throw new Error('waitFor: timeout')
    }
    await new Promise((r) => setTimeout(r, 10))
  }
}

beforeEach(() => {
  reportActions.cancelStreaming()
  reportActions.resetStreaming()
  reportState.current = null
})

afterEach(() => {
  reportActions.cancelStreaming()
  vi.restoreAllMocks()
})

// ── tests ──────────────────────────────────────────────────────────────────

describe('report store — SSE message extraction (extractMessage via startStreaming)', () => {
  it('uses data.summary verbatim when present (plan event)', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        makeSseStream([
          {
            type: 'plan',
            data: {
              summary: '📋 已拆解为 3 个研究维度',
              subtasks: ['基本面', '估值', '风险'],
            },
          },
        ]),
        { status: 200, headers: { 'Content-Type': 'text/event-stream' } },
      ),
    )

    reportActions.startStreaming('rep-1')
    await waitFor(() => reportState.streaming.progress.length >= 1)

    expect(reportState.streaming.progress[0].message).toBe(
      '📋 已拆解为 3 个研究维度',
    )
    expect(fetchSpy).toHaveBeenCalledTimes(1)
  })

  it('falls back to PROGRESS_LABELS when data has no summary (report_chunk → 撰写章节)', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        makeSseStream([
          {
            type: 'report_chunk',
            data: { chunk: '## 标的概览\n...' },
          },
        ]),
        { status: 200 },
      ),
    )

    reportActions.startStreaming('rep-2')
    await waitFor(() => reportState.streaming.progress.length >= 1)

    expect(reportState.streaming.progress[0].message).toBe('撰写章节')
  })

  it('falls back to PROGRESS_LABELS for done event with empty data → 研报完成', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        makeSseStream([
          { type: 'plan', data: { summary: 'kicking off' } },
          { type: 'done', data: {} },
        ]),
        { status: 200 },
      ),
    )
    // done event triggers fetchDetail — stub it so the test doesn't hit network
    vi.spyOn(reportsApi, 'getReport').mockResolvedValue({
      data: {
        id: 'rep-3',
        target_name: 'X',
        target_ts_code: null,
        status: 'completed',
        cost: 0,
        created_at: '',
        updated_at: '',
        request_id: null,
        report_json: {},
      },
    } as Awaited<ReturnType<typeof reportsApi.getReport>>)

    reportActions.startStreaming('rep-3')
    await waitFor(() => reportState.streaming.progress.length >= 2)

    const doneEvt = reportState.streaming.progress.find((p) => p.type === 'done')
    expect(doneEvt?.message).toBe('研报完成')
  })
})

describe('report store — startStreaming SSE pipeline', () => {
  it('accumulates report_chunk into partialSections.report_markdown (overwrite, not concat)', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        makeSseStream([
          { type: 'report_chunk', data: { chunk: '## 第一段\n初稿' } },
          {
            type: 'report_chunk',
            data: { chunk: '## 第一段\n初稿\n## 第二段\n继续' },
          },
        ]),
        { status: 200 },
      ),
    )

    reportActions.startStreaming('rep-stream')
    await waitFor(() => reportState.streaming.progress.length >= 2)

    // writer_node 推送整篇 markdown,所以最后一帧应直接 overwrite,不是 concat.
    expect(reportState.streaming.partialSections.report_markdown).toBe(
      '## 第一段\n初稿\n## 第二段\n继续',
    )
  })

  it('triggers fetchDetail and clears active flag when done event arrives', async () => {
    const detailSpy = vi.spyOn(reportsApi, 'getReport').mockResolvedValue({
      data: {
        id: 'rep-final',
        target_name: '贵州茅台',
        target_ts_code: '600519.SH',
        status: 'completed',
        cost: 0.42,
        created_at: '',
        updated_at: '',
        request_id: 'rid-final',
        report_json: { abstract: 'ok' },
      },
    } as unknown as Awaited<ReturnType<typeof reportsApi.getReport>>)

    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        makeSseStream([
          { type: 'plan', data: { summary: 'plan ok' } },
          { type: 'done', data: { summary: '完成' } },
        ]),
        { status: 200 },
      ),
    )

    reportActions.startStreaming('rep-final')
    await waitFor(
      () =>
        !reportState.streaming.active &&
        reportState.current?.id === 'rep-final',
    )

    expect(reportState.streaming.active).toBe(false)
    expect(detailSpy).toHaveBeenCalledWith('rep-final')
    expect(reportState.current?.target_name).toBe('贵州茅台')
  })
})
