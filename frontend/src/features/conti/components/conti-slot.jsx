import { Button } from "../../../components/ui/button";

// The button names carry the song title (not just "위로"/"아래로") so that a
// screen with several songs never has two buttons sharing one accessible
// name — getByRole("button", { name }) would otherwise have to fall back to
// DOM order, which is exactly what the reorder tests are there to check.
export default function ContiSlot({
  item,
  isFirst,
  isLast,
  disabled,
  slotRatio,
  onMoveUp,
  onMoveDown,
  onEdit,
  onDragStart,
  onDragOver,
  onDrop,
  onDragEnd,
}) {
  // A blank slot starts no drag — there is nothing to pick up — but it does
  // take a drop, and that is the only way to make a page hold one song: with
  // page breaks gone, "put this song on the next page" is spelled as "drop it
  // in that page's empty box".
  if (!item) {
    return (
      <div
        role="group"
        aria-label="빈 칸"
        onDragOver={disabled ? undefined : onDragOver}
        onDrop={disabled ? undefined : onDrop}
        style={{ "--conti-slot-ratio": String(slotRatio) }}
        className="aspect-[var(--conti-slot-ratio)] rounded-md border border-dashed border-stone-200"
      />
    );
  }

  return (
    <div
      role="group"
      aria-label={item.title}
      // draggable follows `disabled` too: gating only the buttons left the
      // drag path open during a save, so a second reorder could be computed
      // from the pre-move list and land after the first response.
      draggable={!disabled}
      onDragStart={disabled ? undefined : onDragStart}
      onDragOver={disabled ? undefined : onDragOver}
      onDrop={disabled ? undefined : onDrop}
      onDragEnd={onDragEnd}
      style={{ "--conti-slot-ratio": String(slotRatio) }}
      className="flex aspect-[var(--conti-slot-ratio)] flex-col gap-2 rounded-md border border-stone-200 p-2"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-sm font-medium text-stone-900">{item.title}</span>
        <div className="flex items-center gap-1">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={disabled || isFirst}
            aria-label={`${item.title} 위로`}
            onClick={onMoveUp}
          >
            위로
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={disabled || isLast}
            aria-label={`${item.title} 아래로`}
            onClick={onMoveDown}
          >
            아래로
          </Button>
          {/* Only when there is a sheet to draw on. image_url is null both for
              a song with no file and for one whose key predates the current
              scheme (presign_score_download answers None for those), and the
              editor would open onto nothing in either case. */}
          {item.image_url ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={disabled}
              aria-label={`${item.title} 편집`}
              onClick={onEdit}
            >
              편집
            </Button>
          ) : null}
        </div>
      </div>
      <div className="flex flex-1 items-center justify-center overflow-hidden">
        {item.image_url ? (
          <img
            src={item.image_url}
            alt={item.title}
            className="max-h-full max-w-full object-contain"
          />
        ) : (
          <p className="text-sm text-stone-500">악보 파일이 없습니다.</p>
        )}
      </div>
    </div>
  );
}
