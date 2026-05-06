/**
 * frontend/src/api/__tests__/reports.test.ts
 *
 * Vitest unit tests for the /reports CRUD client. We mock the shared
 * `request` axios instance (not axios itself) so the servicePlugin envelope
 * unwrap layer is exercised by integration / e2e instead — here we just
 * verify URL + payload + that we forward the response as-is.
 */

import type { AxiosResponse } from 'axios'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { request } from '@/api/request'
import {
  deleteReport,
  getReport,
  listReports,
  startReport,
  type ReportDetail,
  type ReportListResponse,
  type ReportStartResponse,
} from '@/api/reports'

function makeAxiosResponse<T>(data: T, status = 200): AxiosResponse<T> {
  return {
    data,
    status,
    statusText: 'OK',
    headers: {},
    config: {} as AxiosResponse<T>['config'],
  }
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('api/reports — listReports', () => {
  it('GETs /reports with page+page_size params and returns the axios envelope', async () => {
    const payload: ReportListResponse = {
      items: [],
      total: 0,
      page: 2,
      page_size: 50,
    }
    const getSpy = vi
      .spyOn(request, 'get')
      .mockResolvedValue(makeAxiosResponse(payload))

    const res = await listReports(2, 50)

    expect(getSpy).toHaveBeenCalledTimes(1)
    expect(getSpy).toHaveBeenCalledWith('/reports', {
      params: { page: 2, page_size: 50 },
      loading: false,
    })
    expect(res.data).toEqual(payload)
  })
})

describe('api/reports — getReport', () => {
  it('GETs /reports/:id and forwards detail payload', async () => {
    const detail: ReportDetail = {
      id: 'r-1',
      target_name: '招商银行',
      target_ts_code: '600036.SH',
      status: 'completed',
      cost: 0.33,
      created_at: '2026-05-06T00:00:00Z',
      updated_at: '2026-05-06T00:01:00Z',
      request_id: 'req-1',
      report_json: {},
    }
    const getSpy = vi
      .spyOn(request, 'get')
      .mockResolvedValue(makeAxiosResponse(detail))

    const res = await getReport('r-1')

    expect(getSpy).toHaveBeenCalledWith('/reports/r-1', { loading: false })
    expect(res.data.id).toBe('r-1')
    expect(res.data.status).toBe('completed')
  })
})

describe('api/reports — deleteReport', () => {
  it('DELETEs /reports/:id', async () => {
    const delSpy = vi
      .spyOn(request, 'delete')
      .mockResolvedValue(makeAxiosResponse(null, 204))

    await deleteReport('r-2')

    expect(delSpy).toHaveBeenCalledWith('/reports/r-2')
  })
})

describe('api/reports — startReport', () => {
  it('POSTs /reports with target_name + optional fields and returns id', async () => {
    const payload: ReportStartResponse = { id: 'r-new' }
    const postSpy = vi
      .spyOn(request, 'post')
      .mockResolvedValue(makeAxiosResponse(payload))

    const res = await startReport({
      target_name: '贵州茅台',
      target_ts_code: '600519.SH',
      research_style: 'banking',
    })

    expect(postSpy).toHaveBeenCalledWith('/reports', {
      target_name: '贵州茅台',
      target_ts_code: '600519.SH',
      research_style: 'banking',
    })
    expect(res.data.id).toBe('r-new')
  })

  it('POSTs only target_name when optional fields are omitted', async () => {
    const postSpy = vi
      .spyOn(request, 'post')
      .mockResolvedValue(makeAxiosResponse({ id: 'r-min' }))

    await startReport({ target_name: 'X' })

    expect(postSpy).toHaveBeenCalledWith('/reports', {
      target_name: 'X',
      target_ts_code: undefined,
      research_style: undefined,
    })
  })
})
