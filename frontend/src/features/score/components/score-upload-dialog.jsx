import { useEffect, useMemo, useState } from "react";
import { format } from "date-fns";

import DatePicker from "../../../components/DatePicker";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { startOfToday } from "../../../lib/dates";
import SavedScorePicker from "./saved-score-picker";

function getInitialMode(initialMode) {
  if (initialMode) return initialMode;
  return "pc";
}

function getInitialTitle(file) {
  if (!file?.name) return "";
  return file.name.replace(/\.[^/.]+$/, "");
}

function getSavedScoreWeekLabel(score) {
  if (!score?.last_week_of) return "아직 없음";
  return String(score.last_week_of).slice(0, 10);
}

export default function ScoreUploadDialog({
  open,
  onClose,
  onUploadSubmit,
  onApplySavedScore,
  savedScores,
  uploadLoading,
  applyLoading,
  initialMode,
  initialFile,
  initialSavedScore,
}) {
  const [mode, setMode] = useState(getInitialMode(initialMode));
  const [title, setTitle] = useState(() => getInitialTitle(initialFile));
  const [weekOf, setWeekOf] = useState(null);
  // Uploading files the song in the library only; this places it on a Sunday
  // in the same step, through the same placement the library uses.
  const [placeNow, setPlaceNow] = useState(false);
  const [file, setFile] = useState(initialFile ?? null);
  const [selectedSongId, setSelectedSongId] = useState(initialSavedScore?.song_id ?? "");
  const [submitError, setSubmitError] = useState("");
  const previewUrl = useMemo(() => {
    if (!file) return "";
    return URL.createObjectURL(file);
  }, [file]);

  const weekLabel = useMemo(() => {
    if (!weekOf) return "";
    return format(weekOf, "yyyy-MM-dd");
  }, [weekOf]);

  useEffect(() => {
    return () => {
      if (previewUrl) {
        URL.revokeObjectURL(previewUrl);
      }
    };
  }, [previewUrl]);

  if (!open) return null;

  const selectedSavedScore = savedScores.find((score) => score.song_id === selectedSongId) ?? null;
  const isSubmitting = uploadLoading || applyLoading;
  const needsWeek = mode === "library" || placeNow;

  const handleSubmit = async (event) => {
    event.preventDefault();
    let result = null;

    if (mode === "library") {
      if (!selectedSongId || !weekLabel) return;
      result = await onApplySavedScore({
        songId: selectedSongId,
        weekOf: weekLabel,
      });
    } else {
      if (!title || !file || (placeNow && !weekLabel)) return;
      result = await onUploadSubmit({ title, file });
    }

    if (!result?.ok) {
      // The same-week and same-title 409s carry a server-authored detail; it
      // stays on screen and the dialog stays open so the caller can fix the
      // week or title and retry, rather than losing the form.
      setSubmitError(result?.message || "");
      return;
    }

    let placeError = "";
    if (mode === "pc" && placeNow) {
      const placed = await onApplySavedScore({ songId: result.songId, weekOf: weekLabel });
      placeError = placed?.ok ? "" : placed?.message || "주차에 배치하지 못했습니다.";
    }

    onClose();
    setTitle("");
    setWeekOf(null);
    setPlaceNow(false);
    setFile(null);
    setSelectedSongId("");
    setSubmitError("");

    // The song is in the library by now, so the dialog closes even if placing
    // it failed: retrying the upload would only hit the same-title 409.
    if (placeError) {
      window.alert(
        `보관함에는 올렸지만 주차에 배치하지 못했습니다: ${placeError} 보관함에서 골라 다시 배치해 주세요.`
      );
      return;
    }

    window.alert(
      mode === "library"
        ? "콘티에 추가했습니다."
        : placeNow
          ? "보관함에 올리고 주차에 배치했습니다."
          : "보관함에 업로드되었습니다."
    );
  };

  return (
    <div className="fixed inset-0 z-50 bg-stone-950/40 px-4 py-10 backdrop-blur-sm">
      <div className="mx-auto w-full max-w-xl rounded-2xl border border-stone-200 bg-white p-6 shadow-xl">
        <div className="mb-6 flex items-start justify-between gap-4">
          <div>
            <p className="text-xs font-medium uppercase tracking-[0.12em] text-stone-500">
              {mode === "library" ? "콘티에 곡 추가" : "보관함에 업로드"}
            </p>
            <h2 className="mt-1 text-xl font-semibold text-stone-950">
              {mode === "library"
                ? "보관함에서 곡을 골라 콘티에 추가하세요"
                : "보관함에 새 악보를 추가하세요"}
            </h2>
          </div>
          <Button type="button" variant="ghost" size="sm" onClick={onClose}>
            닫기
          </Button>
        </div>

        <form className="space-y-4" onSubmit={handleSubmit}>
          {mode === "library" ? (
            <>
              <div className="space-y-2">
                <Label>보관함 악보</Label>
                <SavedScorePicker
                  scores={savedScores}
                  selectedId={selectedSongId}
                  onSelect={setSelectedSongId}
                  onUploadNew={(query) => {
                    // A song the library does not have yet is uploaded first;
                    // the typed search is the likeliest title for it.
                    setMode("pc");
                    setTitle(query);
                    setSubmitError("");
                  }}
                />
              </div>

              {selectedSavedScore ? (
                <div className="rounded-md border border-stone-200 bg-stone-50 p-3 text-sm text-stone-600">
                  최근 주차 {getSavedScoreWeekLabel(selectedSavedScore)} · 사용{" "}
                  {selectedSavedScore.use_count}회
                </div>
              ) : null}

              <div className="space-y-2">
                <Label>주차 선택</Label>
                {/* The server refuses a Sunday already past (422). */}
                <DatePicker
                  value={weekOf}
                  onChange={setWeekOf}
                  disabled={{ before: startOfToday() }}
                />
              </div>
            </>
          ) : (
            <>
              <div className="space-y-2">
                <Label htmlFor="score-title">악보 제목</Label>
                <Input
                  id="score-title"
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                  placeholder="예: 믿음의 고백"
                  required
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="score-file">이미지 파일</Label>
                <Input
                  id="score-file"
                  type="file"
                  accept="image/*"
                  onChange={(event) => setFile(event.target.files?.[0] || null)}
                  required={!file}
                />
                {file ? <p className="text-xs text-stone-500">선택한 파일: {file.name}</p> : null}
              </div>

              {previewUrl ? (
                <div className="w-fit overflow-hidden rounded-xl border border-stone-200 bg-stone-50">
                  <img
                    src={previewUrl}
                    alt={title || file?.name || "업로드 미리보기"}
                    className="h-40 w-40 object-cover"
                  />
                  <div className="w-40 border-t border-stone-200 bg-white px-3 py-2">
                    <p className="truncate text-sm font-medium text-stone-900">
                      {title || file?.name}
                    </p>
                  </div>
                </div>
              ) : null}

              <label className="flex items-center gap-2 text-sm text-stone-700">
                <input
                  type="checkbox"
                  className="h-4 w-4 rounded border-stone-300"
                  checked={placeNow}
                  onChange={(event) => setPlaceNow(event.target.checked)}
                />
                업로드 후 바로 주차에 배치
              </label>

              {placeNow ? (
                <div className="space-y-2">
                  <Label>주차 선택</Label>
                  {/* Past dates are always a mis-click here: in 140 production
                      uploads every score was filed 1-3 days before its Sunday
                      and none was ever backdated.

                      This week stays reachable — the server files a score under
                      the Sunday opening the week of whatever day is picked, so
                      choosing today lands in the current week. */}
                  <DatePicker
                    value={weekOf}
                    onChange={setWeekOf}
                    disabled={{ before: startOfToday() }}
                  />
                </div>
              ) : null}
            </>
          )}

          {submitError ? (
            <p className="text-sm text-red-600" role="alert">
              {submitError}
            </p>
          ) : null}

          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="outline" onClick={onClose}>
              취소
            </Button>
            <Button
              type="submit"
              disabled={
                isSubmitting ||
                (mode === "library" ? !selectedSongId : !title || !file) ||
                (needsWeek && !weekLabel)
              }
            >
              {mode === "library"
                ? applyLoading
                  ? "추가 중..."
                  : "콘티에 추가"
                : uploadLoading
                  ? "업로드 중..."
                  : "업로드"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
