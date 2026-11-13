import { expect, type Page, test } from '@playwright/test'

/**
 * The three paths that matter to a user: get a plan, change one, take it away.
 * Everything else in the UI is decoration around these.
 */

/** Fill the planner form with the smallest valid input and submit it. */
async function requestPlan(page: Page, city = '杭州') {
  await page.goto('/')
  await page.getByPlaceholder('如：北京').fill(city)
  await page.locator('input[type="date"]').fill('2026-12-01')
  await page.getByPlaceholder('如：3').fill('2')

  // Ant Design's controls have no native <select> to fill: the segmented control
  // and both selects need an explicit click-then-pick. The form item ids
  // (#form_item_*) are the only stable selector Ant Design renders here - the
  // placeholders never reach the DOM.
  await page.locator('.ant-segmented-item', { hasText: '中等' }).click()
  await pickFromSelect(page, 'transportation', '公共交通')
  await pickFromSelect(page, 'accommodation', '经济型酒店')

  await page.getByRole('button', { name: '生成行程' }).click()
}

async function pickFromSelect(page: Page, fieldId: string, option: string) {
  await page.locator(`.ant-select:has(#form_item_${fieldId}) .ant-select-selector`).click()
  // Auto-waiting on the option is enough: it appears once the dropdown expands.
  await page
    .locator('.ant-select-item-option', { hasText: option })
    .first()
    .click({ timeout: 10_000 })
}

/** Wait until the plan is on screen and return its URL. */
async function waitForPlan(page: Page): Promise<string> {
  await page.waitForURL(/\/result\//, { timeout: 60_000 })
  await expect(page.getByText('第 1 天', { exact: true })).toBeVisible()
  return page.url()
}

test('generates a plan and shows it on the result page', async ({ page }) => {
  await requestPlan(page)
  const url = await waitForPlan(page)

  // A two-day request must produce exactly two day cards, and the plan is saved
  // server-side, so the URL carries a real id.
  await expect(page.getByText('第 2 天', { exact: true })).toBeVisible()
  expect(new URL(url).pathname).toMatch(/^\/result\/.+$/)
})

test('edits a day, saves it, and the server keeps the change', async ({ page }) => {
  await requestPlan(page)
  const url = await waitForPlan(page)

  await page.getByRole('button', { name: '编辑行程' }).click()

  const firstDayAttractions = page.locator('article.day-card').first().locator('.attraction-item')
  const before = await firstDayAttractions.count()
  expect(before).toBeGreaterThan(0)

  // Delete the first stop: the trash icon is the last button of the row.
  await firstDayAttractions.first().locator('.edit-buttons button').last().click()
  await page.getByRole('button', { name: '保存' }).click()
  await expect(page.getByText('修改已保存')).toBeVisible()

  // Read it back from the server rather than the sessionStorage cache, which the
  // editor updates locally and would make this assertion meaningless.
  await page.evaluate(() => sessionStorage.clear())
  await page.goto(url)

  await expect(page.locator('article.day-card').first().locator('.attraction-item')).toHaveCount(
    before - 1
  )
})

test('exports the plan as a PDF download', async ({ page }) => {
  await requestPlan(page)
  await waitForPlan(page)

  await page.getByRole('button', { name: '导出' }).click()
  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('menuitem', { name: '导出 PDF' }).click()

  expect((await downloadPromise).suggestedFilename()).toMatch(/\.pdf$/)
})

// --- behaviours the unit tests cannot see: they live in the seam between server
// --- and page, which is exactly where the last round put three regressions.

test('the timetable survives an edit', async ({ page }) => {
  await requestPlan(page)
  const url = await waitForPlan(page)

  const timelineSlots = page.locator('.timeline-slot')
  expect(await timelineSlots.count()).toBeGreaterThan(0)

  await page.getByRole('button', { name: '编辑行程' }).click()
  await page
    .locator('article.day-card')
    .first()
    .locator('.attraction-item')
    .first()
    .locator('.edit-buttons button')
    .last()
    .click()
  await page.getByRole('button', { name: '保存' }).click()
  await expect(page.getByText('修改已保存')).toBeVisible()

  // Reload from the server: the timetable has to be rebuilt for the edited plan,
  // not just carried along in the local copy.
  await page.evaluate(() => sessionStorage.clear())
  await page.goto(url)

  expect(await timelineSlots.count()).toBeGreaterThan(0)
  await expect(timelineSlots.first()).toContainText(/\d{2}:\d{2}–\d{2}:\d{2}/)
})

test('a must-visit that cannot be checked says so instead of pretending', async ({ page }) => {
  await requestPlan(page)

  // The suite runs with USE_SAMPLE_DATA, so the server has no way to resolve the
  // place. It must say that plainly rather than silently dropping the request.
  await page.goto('/')
  await page.getByPlaceholder('如：北京').fill('杭州')
  await page.locator('input[type="date"]').fill('2026-12-01')
  await page.getByPlaceholder('如：3').fill('2')
  await page.locator('.ant-segmented-item', { hasText: '中等' }).click()
  await pickFromSelect(page, 'transportation', '公共交通')
  await pickFromSelect(page, 'accommodation', '经济型酒店')

  const mustVisit = page.locator('.ant-select:has(#form_item_mustVisit) input')
  await mustVisit.fill('西湖')
  await mustVisit.press('Enter')

  await page.getByRole('button', { name: '生成行程' }).click()
  await waitForPlan(page)

  await expect(page.getByText(/必去地点.*未参与校验/)).toBeVisible()
})

test('an arrival time moves the first day\u2019s clock', async ({ page }) => {
  await page.goto('/')
  await page.getByPlaceholder('如：北京').fill('杭州')
  await page.locator('input[type="date"]').fill('2026-12-01')
  await page.getByPlaceholder('如：3').fill('2')
  await page.locator('.ant-segmented-item', { hasText: '中等' }).click()
  await pickFromSelect(page, 'transportation', '公共交通')
  await pickFromSelect(page, 'accommodation', '经济型酒店')

  // Ant Design puts the form item id on the input itself, not on a wrapper.
  await page.locator('#form_item_arrivalTime').fill('15:00')
  await page.getByRole('button', { name: '生成行程' }).click()
  await waitForPlan(page)

  // Not "the timeline exists": the *first slot starts at the arrival time*.
  const firstSlot = page.locator('article.day-card').first().locator('.timeline-slot').first()
  await expect(firstSlot).toContainText(/15:00[–-]/)
})
