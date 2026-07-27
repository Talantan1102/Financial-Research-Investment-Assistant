export function formatDecimalMoney(value: string, digits = 2) {
  if (!Number.isInteger(digits) || digits < 0 || digits > 8) return '—'
  const match = /^([+-]?)(\d+)(?:\.(\d+))?$/.exec(value)
  if (!match || match[2].length > 100) return '—'
  const fraction = match[3] ?? ''
  if (fraction.length > digits) return '—'
  const integer = match[2].replace(/^0+(?=\d)/, '')
  const paddedFraction = fraction.padEnd(digits, '0')
  const isZero =
    /^0+$/.test(integer) &&
    (paddedFraction.length === 0 || /^0+$/.test(paddedFraction))
  const sign = match[1] === '-' && !isZero ? '-' : ''
  const grouped = integer.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  return `${sign}¥${grouped}${digits > 0 ? `.${paddedFraction}` : ''}`
}
