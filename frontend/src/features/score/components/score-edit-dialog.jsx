import { useEffect, useMemo, useState } from "react";

import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";

export default function ScoreEditDialog({ open, score, onClose, onSubmit, loading }) {
  // Seeded once per mount, and the page keys this dialog on the score id — with
  // "none" while closed — so every open is a fresh mount. No effect is needed
  // to resync, and syncing state from an effect would cascade a second render.
  const [title, setTitle] = useState(score?.title ?? "");
  const [file, setFile] = useState(null);
  const [submitError, setSubmitError] = useState("");
  // The page's own alert sits in normal flow, behind this dialog's fixed
  // backdrop, so a failure has to be told here or it is never read.
  const [previewFailed, setPreviewFailed] = useState(false);

  const objectUrl = useMemo(() => {
    if (!file) return "";
    return URL.createObjectURL(file);
  }, [file]);

  useEffect(() => {
    return () => {
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [objectUrl]);

  if (!open || !score) return null;

  // A presigned GET when the score has an s3 key, and the stored URL otherwise
  // — old rows predate the key scheme and resolve to download_url=null.
  const currentUrl = score.download_url ?? score.file_url;
  const previewUrl = objectUrl || currentUrl;
  const trimmedTitle = title.trim();
  const hasChanges = Boolean(file) || trimmedTitle !== score.title;
  const canSubmit = Boolean(trimmedTitle) && hasChanges && !loading;

  const handleFileChange = (event) => {
    setFile(event.target.files?.[0] || null);
    // A local blob is a different image from the one that just failed to load.
    setPreviewFailed(false);
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (!canSubmit) return;

    setSubmitError("");
    const result = await onSubmit({ scoreId: score.id, title: trimmedTitle, file });
    if (result?.ok) {
      onClose();
      return;
    }
    setSubmitError(result?.message ?? "악보 수정에 실패했습니다.");
  };

  return (
    <div className="fixed inset-0 z-50 bg-stone-950/40 px-4 py-10 backdrop-blur-sm">
      <div className="mx-auto w-full max-w-xl rounded-2xl border border-stone-200 bg-white p-6 shadow-xl">
        <div className="mb-6 flex items-start justify-between gap-4">
          <div>
            <p className="text-xs font-medium uppercase tracking-[0.12em] text-stone-500">
              악보 수정
            </p>
            <h2 className="mt-1 text-xl font-semibold text-stone-950">
              제목과 악보 이미지를 바꿉니다
            </h2>
          </div>
          {/* Disabled mid-save, like 취소 below. Closing only unmounts this
              dialog — the promise lives in the page's hook and would finish the
              upload and the PATCH anyway, so an enabled button would read as
              "cancel" while the file was replaced regardless. */}
          <Button type="button" variant="ghost" size="sm" onClick={onClose} disabled={loading}>
            닫기
          </Button>
        </div>

        <form className="space-y-4" onSubmit={handleSubmit}>
          <div className="space-y-2">
            <Label htmlFor="edit-score-title">악보 제목</Label>
            <Input
              id="edit-score-title"
              value={title}
              maxLength={255}
              onChange={(event) => setTitle(event.target.value)}
              required
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="edit-score-file">악보 이미지</Label>
            {/* Optional, unlike the upload dialog: leaving it empty is how the
                caller says "title only", and then no upload URL is requested. */}
            <Input id="edit-score-file" type="file" accept="image/*" onChange={handleFileChange} />
            <p className="text-xs text-stone-500">
              {file ? `새 파일: ${file.name}` : "비워두면 기존 악보를 그대로 둡니다."}
            </p>
          </div>

          {previewUrl && !previewFailed ? (
            <div className="w-fit overflow-hidden rounded-xl border border-stone-200 bg-stone-50">
              {/* onError carries two cases the URL alone cannot tell apart: a
                  presigned GET that expired (they last 15 minutes and the list
                  is fetched once on mount) and a legacy score that is a PDF
                  rather than an image. Both would otherwise render as a broken
                  image icon, since previewUrl is a non-empty string either way. */}
              <img
                src={previewUrl}
                alt={score.title}
                className="max-h-64 object-contain"
                onError={() => setPreviewFailed(true)}
              />
              <div className="border-t border-stone-200 bg-white px-3 py-2">
                <p className="truncate text-sm text-stone-600">
                  {file ? "새 악보 미리보기" : "현재 악보"}
                </p>
              </div>
            </div>
          ) : (
            <div className="rounded-md border border-dashed border-stone-300 p-4 text-sm text-stone-500">
              현재 악보를 미리 볼 수 없습니다. 새 파일을 고르면 그 파일로 교체됩니다.
            </div>
          )}

          {submitError ? (
            <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
              {submitError}
            </p>
          ) : null}

          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="outline" onClick={onClose} disabled={loading}>
              취소
            </Button>
            <Button type="submit" disabled={!canSubmit}>
              {loading ? "저장 중..." : "저장"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
