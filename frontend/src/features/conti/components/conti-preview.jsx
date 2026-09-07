import { useRef } from "react";

import { padSlots, SLOTS_PER_PAGE } from "../../../lib/conti-order";
import ContiSlot from "./conti-slot";

// The browser never re-paginates: `pages` is drawn exactly as the server
// sent it, because chunk_pages on the backend decides where a page breaks
// and a client-side recomputation could disagree with the PDF it is meant to
// preview (DESIGN.md §4-1).
export default function ContiPreview({ pages, slotRatio, isSaving, onReorder, onToggleBreak }) {
  const dragIndexRef = useRef(null);
  const totalItems = pages.reduce((sum, page) => sum + page.length, 0);

  // Carried in a ref instead of dataTransfer: jsdom's fireEvent.drop does not
  // populate dataTransfer, so tests would have to assemble that object by
  // hand. setData is still called (Firefox needs it to start a drag) but
  // never read back.
  const handleDragStart = (index) => (event) => {
    dragIndexRef.current = index;
    event.dataTransfer?.setData("text/plain", String(index));
  };

  const handleDragOver = (event) => {
    event.preventDefault();
  };

  const handleDrop = (index) => (event) => {
    event.preventDefault();
    const from = dragIndexRef.current;
    dragIndexRef.current = null;
    if (from === null) return;
    onReorder(from, index);
  };

  // A drag that ends without a drop (escape, or a drop on a blank slot, which
  // registers no handler) would otherwise leave the index behind, and the next
  // drop — one that never started here — would move that stale song.
  const handleDragEnd = () => {
    dragIndexRef.current = null;
  };

  // Precomputed rather than accumulated in a render-scoped `let`:
  // react-hooks/immutability rejects reassigning one after render completes,
  // and CI runs `pnpm lint` (ci.yml:81), so the mutating form fails the build.
  const pageStartIndices = pages.reduce(
    (acc, page) => [...acc, acc[acc.length - 1] + page.length],
    [0],
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
            className="grid grid-cols-2 gap-4 rounded-lg border border-stone-200 p-4"
          >
            {slots.map((item, slotIndex) => {
              const index = item ? pageStartIndex + slotIndex : null;
              return (
                <ContiSlot
                  key={item ? item.score_id : `empty-${pageIndex}-${slotIndex}`}
                  // A break is stored on the song that starts a page, so the
                  // control belongs to the song it would push down — every
                  // song except the first, whose flag chunk_pages ignores.
                  breakState={
                    index === null || index === 0
                      ? null
                      : item.starts_new_page
                        ? "on"
                        : "off"
                  }
                  onToggleBreak={index === null || index === 0 ? null : () => onToggleBreak(index)}
                  item={item}
                  isFirst={index === 0}
                  isLast={index === totalItems - 1}
                  disabled={isSaving}
                  slotRatio={slotRatio}
                  onMoveUp={() => onReorder(index, index - 1)}
                  onMoveDown={() => onReorder(index, index + 1)}
                  onDragStart={handleDragStart(index)}
                  onDragOver={handleDragOver}
                  onDragEnd={handleDragEnd}
                  onDrop={handleDrop(index)}
                />
              );
            })}
          </section>
        );
      })}
    </div>
  );
}
