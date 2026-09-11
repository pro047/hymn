import { useRef, useState } from "react";

import { Button } from "../../../components/ui/button";
import { useFabricSheet } from "../hooks/use-fabric-sheet";

// Three, not a picker: these are marking colours on a printed sheet, and the
// point of the control is to be pressed without thinking about it.
// `value` is what fabric paints with and what ends up in the stored document,
// so it stays a literal — a class name means nothing to a canvas. `swatch` is
// the same colour spelled for the button, keeping the palette in Tailwind
// rather than in an inline style.
const COLORS = [
  { value: "#dc2626", swatch: "bg-red-600", label: "빨강" },
  { value: "#2563eb", swatch: "bg-blue-600", label: "파랑" },
  { value: "#1c1917", swatch: "bg-stone-900", label: "검정" },
];

const MODES = [
  { value: "draw", label: "그리기" },
  { value: "text", label: "글자" },
  { value: "select", label: "고르기" },
];

/** The editing surface for one song's sheet, on one week.
 *
 * Everything drawn here belongs to this Sunday. The background is the song's
 * own file, so the sheet a leader marks up is always the current one — and
 * replacing that file, or moving this song to another week, drops the markings
 * rather than carrying them somewhere they were not drawn for.
 */
export default function ScoreEditorDialog({
  title,
  sourceImageUrl,
  editDoc,
  hasEdit,
  isLoading,
  isSaving,
  error,
  onSave,
  onClear,
  onClose,
}) {
  const canvasRef = useRef(null);
  const containerRef = useRef(null);
  const [confirmingClear, setConfirmingClear] = useState(false);
  const {
    isReady,
    loadFailed,
    zoomPercent,
    canZoomIn,
    canZoomOut,
    zoomIn,
    zoomOut,
    zoomToFit,
    mode,
    setMode,
    color,
    setColor,
    hasSelection,
    deleteSelected,
    exportSheet,
  } = useFabricSheet({ canvasRef, containerRef, sourceImageUrl, editDoc });

  const busy = isLoading || isSaving;

  const handleSave = async () => {
    const sheet = exportSheet();
    if (!sheet) return;
    const result = await onSave(sheet);
    if (result?.ok) onClose();
  };

  const handleClear = async () => {
    const result = await onClear();
    if (result?.ok) onClose();
  };

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-stone-950/40 px-4 py-10 backdrop-blur-sm">
      <div className="mx-auto w-full max-w-5xl rounded-2xl border border-stone-200 bg-white p-6 shadow-xl">
        <div className="mb-4 flex items-start justify-between gap-4">
          <div>
            <p className="text-xs font-medium uppercase tracking-[0.12em] text-stone-500">
              악보 편집
            </p>
            <h2 className="mt-1 text-xl font-semibold text-stone-950">{title}</h2>
            <p className="mt-1 text-xs text-stone-500">이 주차에만 적용됩니다.</p>
          </div>
          {/* Disabled mid-save for the same reason the score dialog's is: the
              request lives in the page's hook and would finish regardless, so
              an enabled button would read as "cancel" while the sheet saved. */}
          <Button type="button" variant="ghost" size="sm" onClick={onClose} disabled={isSaving}>
            닫기
          </Button>
        </div>

        {error ? (
          <p role="alert" className="mb-4 text-sm text-red-600">
            {error}
          </p>
        ) : null}

        <div className="mb-4 flex flex-wrap items-center gap-2">
          {MODES.map((item) => (
            <Button
              key={item.value}
              type="button"
              size="sm"
              variant={mode === item.value ? "default" : "outline"}
              aria-pressed={mode === item.value}
              disabled={!isReady || busy}
              onClick={() => setMode(item.value)}
            >
              {item.label}
            </Button>
          ))}

          <span aria-hidden="true" className="mx-1 h-5 w-px bg-stone-200" />

          {COLORS.map((item) => (
            <button
              key={item.value}
              type="button"
              aria-label={item.label}
              aria-pressed={color === item.value}
              disabled={!isReady || busy}
              onClick={() => setColor(item.value)}
              className={`h-7 w-7 rounded-full border-2 transition-colors disabled:opacity-40 ${
                item.swatch
              } ${color === item.value ? "border-stone-900" : "border-stone-200"}`}
            />
          ))}

          <span aria-hidden="true" className="mx-1 h-5 w-px bg-stone-200" />

          {/* Disabled rather than hidden: it is the only way to take a stroke
              back, and a control that appears and vanishes as the selection
              changes is harder to find than one that is always in the same
              place. */}
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={!hasSelection || busy}
            onClick={deleteSelected}
          >
            선택 지우기
          </Button>

          {/* Zoom is on the right, away from the tools: it changes what can be
              seen, not what a click does, and grouping it with the brushes
              read as a fourth tool. */}
          <span className="ml-auto flex items-center gap-1">
            <Button
              type="button"
              size="sm"
              variant="outline"
              aria-label="축소"
              disabled={!isReady || !canZoomOut || busy}
              onClick={zoomOut}
            >
              −
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={!isReady || busy}
              onClick={zoomToFit}
            >
              맞춤
            </Button>
            {/* Against the file's own size, so 100% means "as sharp as this
                scan gets". Most scores are under 600px wide, so the fit on a
                full-height box is well under that. */}
            <span className="w-12 text-right text-xs tabular-nums text-stone-500">
              {isReady ? `${zoomPercent}%` : ""}
            </span>
            <Button
              type="button"
              size="sm"
              variant="outline"
              aria-label="확대"
              disabled={!isReady || !canZoomIn || busy}
              onClick={zoomIn}
            >
              +
            </Button>
          </span>
        </div>

        {/* A bounded scroll box, not a section that grows with the sheet. The
            fit above is measured against this element, and while a tool is
            active a drag draws rather than scrolls — so if this could grow,
            an enlarged sheet would have no way to be reached at all. */}
        <div
          ref={containerRef}
          className="flex h-[62vh] items-start justify-center overflow-auto rounded-xl border border-stone-200 bg-stone-50"
        >
          {isLoading ? <p className="p-4 text-sm text-stone-500">악보를 불러오는 중…</p> : null}
          {loadFailed ? (
            <p className="p-4 text-sm text-red-600">악보 이미지를 불러오지 못했습니다.</p>
          ) : null}
          {/* Rendered even while loading: fabric needs the element to exist
              before it can attach, and hiding it behind the spinner would
              leave nothing to attach to. */}
          <canvas ref={canvasRef} aria-label={`${title} 편집 캔버스`} />
        </div>

        <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
          <div>
            {hasEdit && !confirmingClear ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={busy}
                onClick={() => setConfirmingClear(true)}
              >
                원본으로 되돌리기
              </Button>
            ) : null}
            {/* Confirmed in place rather than through window.confirm: this
                throws away work that cannot be recovered, and a native dialog
                is the one control on this screen that tests cannot press. */}
            {hasEdit && confirmingClear ? (
              <span className="flex items-center gap-2 text-sm text-stone-700">
                이 주차의 편집을 모두 지웁니다.
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={busy}
                  onClick={handleClear}
                >
                  지우기
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  disabled={busy}
                  onClick={() => setConfirmingClear(false)}
                >
                  그만두기
                </Button>
              </span>
            ) : null}
          </div>

          <Button type="button" disabled={!isReady || busy} onClick={handleSave}>
            {isSaving ? "저장하는 중…" : "저장"}
          </Button>
        </div>
      </div>
    </div>
  );
}
