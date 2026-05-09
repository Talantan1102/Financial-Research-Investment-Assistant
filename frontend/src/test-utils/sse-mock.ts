/**
 * frontend/src/test-utils/sse-mock.ts
 *
 * Build msw-compatible Response objects that emit SSE events.
 * Each event:  id: <seq>\nevent: <type>\ndata: <json>\n\n
 */

import type { SSEEvent } from '@/types/chat'

export function encodeSSE(events: SSEEvent[]): string {
  return events
    .map((ev) => {
      const data = JSON.stringify(ev)
      return `id: ${ev.seq}\nevent: ${ev.type}\ndata: ${data}\n\n`
    })
    .join('')
}

export function sseResponse(events: SSEEvent[]): Response {
  return new Response(encodeSSE(events), {
    status: 200,
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
    },
  })
}

/**
 * Returns a Response whose body is a ReadableStream we can drive manually.
 * Tests call `.push(ev)` to emit, `.disconnect()` to close.
 */
export function controllableSseResponse(): {
  response: Response
  push: (ev: SSEEvent) => void
  disconnect: () => void
} {
  const encoder = new TextEncoder()
  let controller: ReadableStreamDefaultController<Uint8Array> | null = null
  const stream = new ReadableStream<Uint8Array>({
    start(c) {
      controller = c
    },
  })
  return {
    response: new Response(stream, {
      status: 200,
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
      },
    }),
    push(ev: SSEEvent) {
      const chunk = `id: ${ev.seq}\nevent: ${ev.type}\ndata: ${JSON.stringify(ev)}\n\n`
      controller?.enqueue(encoder.encode(chunk))
    },
    disconnect() {
      controller?.close()
    },
  }
}
