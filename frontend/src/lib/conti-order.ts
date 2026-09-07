// SLOTS_PER_PAGE mirrors services/conti_pdf.SLOTS_PER_PAGE on the backend.
// ContiResponse does not carry this value, so a change there requires a
// matching change here — see DESIGN.md §7 risk 1.
export const SLOTS_PER_PAGE = 2;

export type ContiItem = {
  score_id: string;
  title: string;
  starts_new_page: boolean;
  image_url: string | null;
};

export type ContiOrderPayloadItem = {
  score_id: string;
  starts_new_page: boolean;
};

export function flattenPages(pages: readonly (readonly ContiItem[])[]): ContiItem[] {
  return pages.flatMap((page) => [...page]);
}

// Inserts, not swaps: the item at `from` is removed and the rest shift to
// close the gap, then it is spliced back in at `to`. Returning the same
// reference for a no-op move lets callers skip the PATCH by checking `===`.
export function moveItem<T>(items: readonly T[], from: number, to: number): readonly T[] {
  const inRange = (index: number) => index >= 0 && index < items.length;
  if (from === to || !inRange(from) || !inRange(to)) return items;

  const next = items.slice();
  const [moved] = next.splice(from, 1);
  next.splice(to, 0, moved);
  return next;
}

// Length is max(slots, page.length): a page longer than the usual slot count
// still renders every song instead of dropping the overflow.
export function padSlots<T>(page: readonly T[], slots: number = SLOTS_PER_PAGE): (T | null)[] {
  const length = Math.max(slots, page.length);
  return Array.from({ length }, (_, index) => page[index] ?? null);
}

/**
 * Flips the page break on the item at `index`.
 *
 * Index 0 returns the same reference: chunk_pages ignores a break on the first
 * item (it already starts a page), so letting it toggle would store a flag
 * that changes nothing and show a control that does nothing. Callers skip the
 * PATCH on `===`, the same contract moveItem uses.
 */
export function togglePageBreak(
  items: readonly ContiItem[],
  index: number,
): readonly ContiItem[] {
  if (index <= 0 || index >= items.length) return items;
  return items.map((item, i) =>
    i === index ? { ...item, starts_new_page: !item.starts_new_page } : item,
  );
}

// starts_new_page is relayed as given: moveItem never touches it, and
// togglePageBreak is the only thing that decides it.
export function toOrderPayload(items: readonly ContiItem[]): ContiOrderPayloadItem[] {
  return items.map(({ score_id, starts_new_page }) => ({ score_id, starts_new_page }));
}
