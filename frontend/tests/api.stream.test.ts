import { describe, expect, it, vi } from 'vitest'

// api.ts reads `window.location.origin` and `window.localStorage` at module
// scope, so these stubs must exist before the module is imported (node env).
vi.stubGlobal('window', {
  location: { origin: 'http://127.0.0.1:8000' },
  localStorage: {
    getItem: () => null,
    setItem: () => undefined,
    removeItem: () => undefined
  }
})

async function loadApi() {
  return import('../src/services/api')
}

function sseResponse(frames: string[]): Response {
  const encoder = new TextEncoder()
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const frame of frames) controller.enqueue(encoder.encode(frame))
      controller.close()
    }
  })
  return new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
}

function payload() {
  return { city: '杭州', start_date: '2026-11-20', days: 2 } as never
}

describe('streamTripPlan', () => {
  it('parses stage, heartbeat and plan events', async () => {
    const { streamTripPlan } = await loadApi()
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        sseResponse([
          'event: stage\ndata: {"stage":"create_plan","status":"start"}\n\n',
          'event: heartbeat\ndata: {"elapsed_ms":5000}\n\n',
          'event: plan\ndata: {"plan":{"id":"p1","city":"杭州"}}\n\n'
        ])
      )
    )

    const stages: string[] = []
    const beats: number[] = []
    let city = ''

    await streamTripPlan(payload(), {
      onStage: (event) => stages.push(event.stage),
      onHeartbeat: (elapsed) => beats.push(elapsed),
      onPlan: (plan) => {
        city = (plan as unknown as { city: string }).city
      },
      onError: (detail) => {
        throw new Error(`unexpected error: ${detail}`)
      }
    })

    expect(stages).toEqual(['create_plan'])
    expect(beats).toEqual([5000])
    expect(city).toBe('杭州')
  })

  it('skips a malformed frame instead of killing a healthy stream', async () => {
    const { streamTripPlan } = await loadApi()
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        sseResponse([
          'event: stage\ndata: {not json}\n\n',
          'event: stage\ndata: {"stage":"review_plan","status":"done"}\n\n',
          'event: plan\ndata: {"plan":{"id":"p2","city":"成都"}}\n\n'
        ])
      )
    )

    const stages: string[] = []
    let planned = false

    await streamTripPlan(payload(), {
      onStage: (event) => stages.push(event.stage),
      onPlan: () => {
        planned = true
      },
      onError: (detail) => {
        throw new Error(`unexpected error: ${detail}`)
      }
    })

    expect(stages).toEqual(['review_plan'])
    expect(planned).toBe(true)
  })

  it('reports an abort through onAborted, not onError', async () => {
    const { streamTripPlan } = await loadApi()
    vi.stubGlobal(
      'fetch',
      vi.fn().mockRejectedValue(new DOMException('The operation was aborted.', 'AbortError'))
    )

    let aborted = false
    let errored = false

    await streamTripPlan(
      payload(),
      {
        onPlan: () => undefined,
        onError: () => {
          errored = true
        },
        onAborted: () => {
          aborted = true
        }
      },
      new AbortController().signal
    )

    expect(aborted).toBe(true)
    expect(errored).toBe(false)
  })

  it('surfaces the server explanation instead of a bare HTTP status', async () => {
    const { streamTripPlan } = await loadApi()
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: [{ msg: 'city must not be blank' }] }), {
          status: 422,
          headers: { 'Content-Type': 'application/json' }
        })
      )
    )

    let detail = ''

    await streamTripPlan(payload(), {
      onPlan: () => undefined,
      onError: (message) => {
        detail = message
      }
    })

    expect(detail).toBe('city must not be blank')
  })

  it('passes the abort signal to fetch so the server can stop producing', async () => {
    const { streamTripPlan } = await loadApi()
    const fetchMock = vi.fn().mockResolvedValue(sseResponse([]))
    vi.stubGlobal('fetch', fetchMock)
    const controller = new AbortController()

    await streamTripPlan(
      payload(),
      { onPlan: () => undefined, onError: () => undefined },
      controller.signal
    )

    const init = fetchMock.mock.calls[0][1] as RequestInit
    expect(init.signal).toBe(controller.signal)
  })
})
