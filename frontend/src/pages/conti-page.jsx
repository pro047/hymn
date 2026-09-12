import { useState } from "react";
import { useParams } from "react-router-dom";

import { Alert, AlertDescription, AlertTitle } from "../components/ui/alert";
import { Button } from "../components/ui/button";
import ContiPreview from "../features/conti/components/conti-preview";
import ScoreEditorDialog from "../features/conti/components/score-editor-dialog";
import { useConti } from "../features/conti/hooks/use-conti";
import { useScoreEdit } from "../features/conti/hooks/use-score-edit";

export default function ContiPage() {
  const { week } = useParams();
  const {
    weekOf,
    pages,
    slotRatio,
    isLoading,
    isSaving,
    isDownloading,
    error,
    moveSlot,
    splitPage,
    downloadPdf,
    refresh,
  } = useConti(week);

  // The whole conti item, not just its id: the dialog needs the title too,
  // and it is already on screen — asking the server for it again would be a
  // round trip for something this component is holding.
  const [editing, setEditing] = useState(null);
  const edit = useScoreEdit(editing?.score_id ?? null);

  const handleEdit = (item) => setEditing(item);
  const handleCloseEditor = () => setEditing(null);

  // Refreshed after the dialog closes, not instead of closing it: the preview
  // reads image_url off the conti response, and that URL only changes once the
  // server has been told about the new sheet.
  const handleSaveEdit = async (sheet) => {
    const result = await edit.save(sheet);
    if (result?.ok) await refresh();
    return result;
  };

  const handleClearEdit = async () => {
    const result = await edit.clear();
    if (result?.ok) await refresh();
    return result;
  };

  // The PDF endpoint answers 404 for an empty week (routes/conti.py:48-49),
  // so the button is not rendered rather than offered and turned into an
  // error — "no songs" is not a failure (DESIGN.md §4-6).
  const hasSongs = Boolean(pages && pages.length > 0);
  // Same reasoning one step further: build_week_conti_pdf refuses the whole
  // week with a 502 if any song has no file (services/conti.py), and the
  // preview already knows which ones those are. Offering a button that can
  // only fail is worse than saying why it is not there.
  const songsWithoutFile = (pages ?? [])
    .flat()
    .filter((item) => !item.image_url)
    .map((item) => item.title);
  const canMakePdf = hasSongs && songsWithoutFile.length === 0;

  return (
    <div className="min-h-screen bg-white text-stone-900">
      <header className="border-b border-stone-200 bg-white/95 backdrop-blur">
        <div className="mx-auto flex w-full max-w-6xl flex-col gap-2 px-4 py-4 sm:px-6 md:flex-row md:items-center md:justify-between lg:px-8">
          <h1 className="text-base font-semibold tracking-tight text-stone-950">{weekOf} 콘티</h1>
          {canMakePdf ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={isDownloading}
              onClick={downloadPdf}
            >
              {isDownloading ? "PDF 만드는 중…" : "PDF 내려받기"}
            </Button>
          ) : hasSongs ? (
            <p className="text-xs text-stone-500">
              악보 파일이 없는 곡이 있어 PDF를 만들 수 없습니다: {songsWithoutFile.join(", ")}
            </p>
          ) : null}
        </div>
      </header>

      <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 px-4 py-8 sm:px-6 lg:px-8">
        {error ? (
          <Alert variant="destructive">
            <AlertTitle>요청 실패</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : null}

        {isLoading ? (
          <p className="text-sm text-stone-500">콘티를 불러오는 중…</p>
        ) : pages && pages.length === 0 ? (
          <div className="rounded-md border border-dashed border-stone-300 p-4 text-sm text-stone-500">
            아직 등록된 곡이 없습니다.
          </div>
        ) : (
          <ContiPreview
            pages={pages ?? []}
            slotRatio={slotRatio}
            isSaving={isSaving}
            onMove={moveSlot}
            onSplit={splitPage}
            onEdit={handleEdit}
          />
        )}
      </div>

      {/* Keyed on the score so switching songs remounts the dialog: the canvas
          is seeded from edit_doc once, on mount, and a reused instance would
          keep the previous song's markings. */}
      {editing ? (
        <ScoreEditorDialog
          key={editing.score_id}
          title={editing.title}
          sourceImageUrl={edit.sourceImageUrl}
          editDoc={edit.editDoc}
          hasEdit={edit.hasEdit}
          isLoading={edit.isLoading}
          isSaving={edit.isSaving}
          error={edit.error}
          onSave={handleSaveEdit}
          onClear={handleClearEdit}
          onClose={handleCloseEditor}
        />
      ) : null}
    </div>
  );
}
