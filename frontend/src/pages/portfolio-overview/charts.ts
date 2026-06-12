import { pnlColor } from '@/utils/pnl-color'
import type { ChartConfig } from '@/components/chart'

const CLASS_LABEL: Record<string, string> = {
  stock: '股票',
  fund_etf: '场内ETF',
  fund_otc: '场外基金',
  bond: '债基',
  gold: '黄金',
  cash: '现金',
}

export function structurePie(byClass: Record<string, number>): ChartConfig {
  return {
    type: 'pie',
    title: '',
    echarts_option: {
      tooltip: { trigger: 'item', formatter: '{b}: {d}%' },
      series: [
        {
          type: 'pie',
          radius: ['45%', '70%'],
          data: Object.entries(byClass).map(([k, v]) => ({
            name: CLASS_LABEL[k] ?? k,
            value: Math.round(v * 1000) / 10,
          })),
        },
      ],
    },
  }
}

export function trendLine(
  dates: string[],
  portfolio: number[],
  benchmark: number[],
  cumulative: number,
): ChartConfig {
  return {
    type: 'line',
    title: '',
    echarts_option: {
      color: [pnlColor(cumulative), '#c7c7cc'],
      tooltip: { trigger: 'axis' },
      legend: { data: ['我的整盘', '沪深300'] },
      xAxis: { type: 'category', data: dates },
      yAxis: { type: 'value' },
      series: [
        {
          name: '我的整盘',
          type: 'line',
          smooth: true,
          data: portfolio.map((x) => +(x * 100).toFixed(2)),
        },
        {
          name: '沪深300',
          type: 'line',
          smooth: true,
          data: benchmark.map((x) => +(x * 100).toFixed(2)),
        },
      ],
    },
  }
}
