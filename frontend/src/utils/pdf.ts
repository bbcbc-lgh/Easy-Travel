export interface PageSlice {
  offsetY: number
  height: number
}

/**
 * Split a tall canvas into A4-sized slices instead of shrinking it onto one page.
 * Sizes are in canvas pixels; the caller scales each slice to the printable width.
 */
export function paginateCanvas(
  canvasWidth: number,
  canvasHeight: number,
  pageWidthMm = 210,
  pageHeightMm = 297,
  marginMm = 8
): PageSlice[] {
  if (canvasWidth <= 0 || canvasHeight <= 0) return []

  const contentWidthMm = pageWidthMm - marginMm * 2
  const contentHeightMm = pageHeightMm - marginMm * 2
  if (contentWidthMm <= 0 || contentHeightMm <= 0) return []

  const pxPerMm = canvasWidth / contentWidthMm
  const pageHeightPx = Math.max(1, Math.floor(contentHeightMm * pxPerMm))

  const slices: PageSlice[] = []
  for (let offsetY = 0; offsetY < canvasHeight; offsetY += pageHeightPx) {
    slices.push({ offsetY, height: Math.min(pageHeightPx, canvasHeight - offsetY) })
  }
  return slices
}
