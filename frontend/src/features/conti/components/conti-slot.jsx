import { Button } from "../../../components/ui/button";

// The scissors sits on the song a break would push onto a new page, which is
// how the server stores it. null means this slot cannot carry one: a blank
// slot, or the very first song (chunk_pages ignores a break there).
function BreakControl({ state, title, disabled, onToggle }) {
  if (!state) return null;
  const on = state === "on";
  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      disabled={disabled}
      aria-label={on ? `${title} 앞 나누기 해제` : `${title} 앞에서 나누기`}
      onClick={onToggle}
      className={on ? "text-xs text-stone-900" : "text-xs text-stone-400"}
    >
      {on ? "✂ 나누기 해제" : "✂ 여기서 나누기"}
    </Button>
  );
}

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
  onDragStart,
  onDragOver,
  onDrop,
  onDragEnd,
  breakState,
  onToggleBreak,
}) {
  // A blank slot is "no song here", not a position: it accepts no drag and no
  // drop, so the same gesture never has to mean two different things
  // depending on which empty slot it lands on (DESIGN.md §4-5).
  if (!item) {
    return (
      <div
        role="group"
        aria-label="빈 칸"
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
      <BreakControl
        state={breakState}
        title={item.title}
        disabled={disabled}
        onToggle={onToggleBreak}
      />
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
