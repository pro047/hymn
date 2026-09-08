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

export type ContiPages = readonly (readonly ContiItem[])[];

// Which box on screen, not which song: `slot` counts padded slots, so it can
// name a blank one. That is the point — dropping onto a blank is how a song
// leaves a page it was sharing.
export type SlotPosition = { readonly page: number; readonly slot: number };

export type ContiOrderPayloadItem = {
  score_id: string;
  starts_new_page: boolean;
};

// Length is max(slots, page.length): a page longer than the usual slot count
// still renders every song instead of dropping the overflow.
export function padSlots<T>(page: readonly T[], slots: number = SLOTS_PER_PAGE): (T | null)[] {
  const length = Math.max(slots, page.length);
  return Array.from({ length }, (_, index) => page[index] ?? null);
}

function itemAt(pages: ContiPages, position: SlotPosition): ContiItem | null {
  return pages[position.page]?.[position.slot] ?? null;
}

// Compared by score_id and by shape, not by object identity: the swap branch
// reuses the very objects it received, so a deep-equal check on references
// would call an actual swap a no-op.
function sameLayout(a: ContiPages, b: ContiPages): boolean {
  return (
    a.length === b.length &&
    a.every(
      (page, pageIndex) =>
        page.length === b[pageIndex].length &&
        page.every((item, slotIndex) => item.score_id === b[pageIndex][slotIndex].score_id)
    )
  );
}

/**
 * Moves the song at `from` into the box at `to` and answers the new layout.
 *
 * Two moves, told apart by what already sits in the target box:
 *   - a song   -> the two trade places, and neither page changes size
 *   - a blank  -> the song moves in, and the page it left shrinks
 *
 * Sizes are the reason for the split. chunk_pages caps a page at
 * SLOTS_PER_PAGE, so a layout with three songs on one page cannot be
 * reproduced by the server and the preview would stop matching the PDF — the
 * one thing this screen exists to promise. A trade cannot grow a page, and a
 * blank box only exists on a page with room, so neither branch can overflow.
 *
 * A page emptied by the move is dropped rather than left behind: an empty page
 * has no box to drop onto and would print as a blank sheet.
 *
 * Returns the input unchanged when nothing moves, so callers can skip the
 * PATCH on `===`.
 */
export function moveInGrid(pages: ContiPages, from: SlotPosition, to: SlotPosition): ContiPages {
  const moved = itemAt(pages, from);
  if (!moved || !pages[to.page]) return pages;
  if (from.page === to.page && from.slot === to.slot) return pages;

  const target = itemAt(pages, to);
  if (target) {
    return pages.map((page, pageIndex) =>
      page.map((item, slotIndex) => {
        if (pageIndex === from.page && slotIndex === from.slot) return target;
        if (pageIndex === to.page && slotIndex === to.slot) return moved;
        return item;
      })
    );
  }

  const next = pages.map((page) => [...page]);
  next[from.page].splice(from.slot, 1);
  // `to.slot` counts padded slots, so it can sit past the end of the page once
  // the splice above has shortened it. splice appends in that case, which is
  // where the blank was anyway — a blank is only ever the tail of a page.
  next[to.page].splice(to.slot, 0, moved);

  const pruned = next.filter((page) => page.length > 0);
  return sameLayout(pages, pruned) ? pages : pruned;
}

/**
 * Where each song sits, in conti order.
 *
 * The up/down buttons need this because "the next song" is not "the next box":
 * a page cut short leaves a blank between two songs, and stepping into it
 * would be a move that changes nothing on a button that looked available.
 */
export function songPositions(pages: ContiPages): SlotPosition[] {
  return pages.flatMap((page, pageIndex) =>
    page.map((_, slotIndex) => ({ page: pageIndex, slot: slotIndex }))
  );
}

/**
 * Flattens the layout and rewrites every break to match it.
 *
 * starts_new_page is an output, not something the leader sets: the box a song
 * was dropped in decides it. First on its page means it starts one; anything
 * else means it does not. chunk_pages replays exactly this rule — a break cuts
 * a page, a full page cuts itself — so the layout that comes back is the
 * layout that was dropped, box for box.
 *
 * The first song is always false: chunk_pages ignores a break there and
 * set_week_order refuses to store one (services/conti.py), so true would be a
 * value nothing reads.
 */
export function withPageBreaks(pages: ContiPages): ContiItem[] {
  return pages.flatMap((page, pageIndex) =>
    page.map((item, slotIndex) => ({
      ...item,
      starts_new_page: pageIndex > 0 && slotIndex === 0,
    }))
  );
}

/**
 * Cuts a new page open in front of the song at `position`.
 *
 * This is the one edit dragging cannot express: it moves no song, it only
 * moves a boundary. `[A,B|C,D]` -> `[A|B,C|D]` leaves the running order
 * untouched, and a gesture that carries a song somewhere else cannot say it.
 * Worse, a drop needs a blank box to aim at, and a week with an even number of
 * songs has none — every page is full — so without this the split is not
 * merely awkward there but unreachable.
 *
 * Unlike the drag path this does NOT go through withPageBreaks. The flags the
 * server sent are the breaks somebody actually asked for; the rest of the
 * layout is chunk_pages filling pages up. Rebuilding the flags from the
 * layout would freeze those automatic seams into requested ones, and cutting
 * `[A,B|C,D]` at B would answer `[A|B|C,D]` — the leader asked for one cut and
 * got two. Dragging normalises because there the whole point is to pin the
 * boxes; here the point is to add a single seam and leave the rest alone.
 *
 * Answers null when there is nothing to cut: the first song of the conti (it
 * already starts a page) or a song that already carries a break — both are
 * places the control is not drawn.
 */
export function splitPageAt(pages: ContiPages, position: SlotPosition): ContiItem[] | null {
  const index = songPositions(pages).findIndex(
    (candidate) => candidate.page === position.page && candidate.slot === position.slot
  );
  if (index <= 0) return null;

  const items = pages.flatMap((page) => [...page]);
  if (items[index].starts_new_page) return null;
  return items.map((item, i) => (i === index ? { ...item, starts_new_page: true } : item));
}

// starts_new_page is relayed as given; withPageBreaks is the only thing that
// decides it.
export function toOrderPayload(items: readonly ContiItem[]): ContiOrderPayloadItem[] {
  return items.map(({ score_id, starts_new_page }) => ({ score_id, starts_new_page }));
}
