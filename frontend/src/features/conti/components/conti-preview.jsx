import { Fragment, useRef } from "react";

import { padSlots, SLOTS_PER_PAGE, songPositions } from "../../../lib/conti-order";
import ContiSlot from "./conti-slot";

// Sits on the boundary *between* two songs of one page, never inside a song's
// card and never between pages. Inside a card it read as "this song's button"
// rather than "this seam"; between pages there would be nothing to cut, since
// that page already starts there — closing a split back up is what dragging a
// song into a blank box does.
// Drawn as a dashed seam with a chip on it, not a bare glyph: at
// text-stone-300 the ✂ alone was invisible until hovered, and on a full week
// the scissors is the *only* way to split — padSlots emits a blank just on the
// short last page, so every earlier page can be cut here or not at all.
// The dashed line borrows the blank slot's border-dashed, which already reads
// as "a place, not a thing" on this screen.
function PageBreakControl({ title, disabled, onSplit }) {
  return (
    <button
      type="button"
      disabled={disabled}
      aria-label={`${title} 앞에서 나누기`}
      onClick={onSplit}
      className="group relative flex w-6 shrink-0 items-center justify-center disabled:pointer-events-none disabled:opacity-40"
    >
      <span
        aria-hidden="true"
        className="absolute inset-y-3 left-1/2 w-px -translate-x-1/2 border-l border-dashed border-stone-300 transition-colors group-hover:border-stone-500"
      />
      <span
        aria-hidden="true"
        className="relative flex h-6 w-6 items-center justify-center rounded-full border border-stone-300 bg-white text-xs leading-none text-stone-600 transition-colors group-hover:border-stone-500 group-hover:bg-stone-100 group-hover:text-stone-900"
      >
        ✂
      </span>
    </button>
  );
}

// The browser never re-paginates: `pages` is drawn exactly as the server
// sent it, because chunk_pages on the backend decides where a page breaks
// and a client-side recomputation could disagree with the PDF it is meant to
// preview (DESIGN.md §4-1).
//
// Two ways to edit, and they do different jobs. Dragging moves a song into a
// box, and the breaks are then read back out of the layout
// (lib/conti-order.withPageBreaks) — nobody sets them by hand. The scissors
// does the one thing that leaves every song where it is: it moves a boundary.
export default function ContiPreview({ pages, slotRatio, isSaving, onMove, onSplit }) {
  const dragFromRef = useRef(null);

  // Songs only, blanks skipped: this is what the up/down buttons step through,
  // because the box before a song is not always another song.
  const positions = songPositions(pages);

  // Carried in a ref instead of dataTransfer: jsdom's fireEvent.drop does not
  // populate dataTransfer, so tests would have to assemble that object by
  // hand. setData is still called (Firefox needs it to start a drag) but
  // never read back.
  const handleDragStart = (position) => (event) => {
    dragFromRef.current = position;
    event.dataTransfer?.setData("text/plain", `${position.page}:${position.slot}`);
  };

  const handleDragOver = (event) => {
    event.preventDefault();
  };

  const handleDrop = (position) => (event) => {
    event.preventDefault();
    const from = dragFromRef.current;
    dragFromRef.current = null;
    if (!from) return;
    onMove(from, position);
  };

  // A drag that ends without a drop (escape, or a drop outside the preview)
  // would otherwise leave the position behind, and the next drop — one that
  // never started here — would move that stale song.
  const handleDragEnd = () => {
    dragFromRef.current = null;
  };

  // Precomputed rather than accumulated in a render-scoped `let`:
  // react-hooks/immutability rejects reassigning one after render completes,
  // and CI runs `pnpm lint` (ci.yml:81), so the mutating form fails the build.
  const pageStartIndices = pages.reduce(
    (acc, page) => [...acc, acc[acc.length - 1] + page.length],
    [0]
  );

  return (
    <div className="space-y-4">
      {pages.map((page, pageIndex) => {
        const pageStartIndex = pageStartIndices[pageIndex];
        const slots = padSlots(page, SLOTS_PER_PAGE);

        return (
          <section
            key={pageIndex}
            aria-label={`${pageIndex + 1}쪽`}
            className="flex items-stretch gap-2 rounded-lg border border-stone-200 p-4"
          >
            {slots.map((item, slotIndex) => {
              const position = { page: pageIndex, slot: slotIndex };
              // Where this song stands in the conti, which is not slotIndex:
              // a page cut short makes the two disagree from there on.
              const songIndex = item ? pageStartIndex + slotIndex : -1;
              return (
                <Fragment key={item ? item.score_id : `empty-${pageIndex}-${slotIndex}`}>
                  {/* Only in front of a song that is not opening the page:
                      slotIndex 0 already starts one, and a blank box has no
                      song to push down. */}
                  {slotIndex > 0 && item ? (
                    <PageBreakControl
                      title={item.title}
                      disabled={isSaving}
                      onSplit={() => onSplit(position)}
                    />
                  ) : null}
                  <div className="min-w-0 flex-1">
                    <ContiSlot
                      item={item}
                      isFirst={songIndex === 0}
                      isLast={songIndex === positions.length - 1}
                      disabled={isSaving}
                      slotRatio={slotRatio}
                      // Up and down trade places with the neighbouring *song*,
                      // stepping over any blank between them. Moving into the
                      // blank instead would leave the conti in the same order
                      // and the same pages — a button that looked available
                      // and did nothing.
                      onMoveUp={() => onMove(position, positions[songIndex - 1])}
                      onMoveDown={() => onMove(position, positions[songIndex + 1])}
                      onDragStart={handleDragStart(position)}
                      onDragOver={handleDragOver}
                      onDragEnd={handleDragEnd}
                      onDrop={handleDrop(position)}
                    />
                  </div>
                </Fragment>
              );
            })}
          </section>
        );
      })}
    </div>
  );
}
