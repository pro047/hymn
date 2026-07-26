import { useEffect, useMemo, useState } from "react";
import { format } from "date-fns";

import DatePicker from "../../../components/DatePicker";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";

function getInitialMode(initialMode) {
  if (initialMode) return initialMode;
  return "pc";
}

function getInitialTitle(file) {
  if (!file?.name) return "";
  return file.name.replace(/\.[^/.]+$/, "");
}

function getSavedScoreWeekLabel(score) {
  if (!score?.week_of) return "주차 미지정";
  return String(score.week_of).slice(0, 10);
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
  lockMode = false,
  saveToLibrary = false,
}) {
  const [mode, setMode] = useState(getInitialMode(initialMode));
  const [title, setTitle] = useState(() => getInitialTitle(initialFile));
  const [churchName, setChurchName] = useState("");
  const [weekOf, setWeekOf] = useState(null);
  const [file, setFile] = useState(initialFile ?? null);
  const [selectedSavedScoreId, setSelectedSavedScoreId] = useState(
    initialSavedScore?.score_id ?? ""
  );
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

  const selectedSavedScore =
    savedScores.find((score) => score.score_id === selectedSavedScoreId) ?? null;
  const isSubmitting = mode === "library" ? applyLoading : uploadLoading;
  const isLibraryUpload = mode === "pc" && saveToLibrary;

  const handleSubmit = async (event) => {
    event.preventDefault();
    let result = null;

    if (mode === "library") {
      if (!selectedSavedScoreId || !weekLabel) return;
      result = await onApplySavedScore({
        scoreId: selectedSavedScoreId,
        weekOf: weekLabel,
      });
    } else {
      const normalizedChurchName = churchName.replace(/\s+/g, "");
      if (!title || !file || (!isLibraryUpload && (!normalizedChurchName || !weekOf))) return;
      result = await onUploadSubmit({
        title,
        churchName: normalizedChurchName,
        weekOf: weekLabel,
        file,
        saveToLibrary,
      });
    }

    if (result?.ok) {
      onClose();
      setTitle("");
      setChurchName("");
      setWeekOf(null);
      setFile(null);
      setSelectedSavedScoreId("");
      window.alert(
        mode === "library"
          ? "선택한 악보를 반영했습니다."
          : saveToLibrary
            ? "보관함에 업로드되었습니다."
            : "업로드가 완료되었습니다."
      );
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-stone-950/40 px-4 py-10 backdrop-blur-sm">
      <div className="mx-auto w-full max-w-xl rounded-2xl border border-stone-200 bg-white p-6 shadow-xl">
        <div className="mb-6 flex items-start justify-between gap-4">
          <div>
            <p className="text-xs font-medium uppercase tracking-[0.12em] text-stone-500">
              악보 업로드
            </p>
            <h2 className="mt-1 text-xl font-semibold text-stone-950">
              {mode === "library"
                ? "보관함 악보를 다시 반영하세요"
                : saveToLibrary
                  ? "보관함에 새 악보를 추가하세요"
                  : "새 악보를 등록하세요"}
            </h2>
          </div>
          <Button type="button" variant="ghost" size="sm" onClick={onClose}>
            닫기
          </Button>
        </div>

        <form className="space-y-4" onSubmit={handleSubmit}>
          {!lockMode ? (
            <div className="space-y-2">
              <Label>추가 방식</Label>
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  variant={mode === "library" ? "default" : "outline"}
                  onClick={() => setMode("library")}
                >
                  보관함
                </Button>
                <Button
                  type="button"
                  variant={mode === "pc" ? "default" : "outline"}
                  onClick={() => setMode("pc")}
                >
                  PC 업로드
                </Button>
              </div>
            </div>
          ) : null}

          {mode === "library" ? (
            <>
              <div className="space-y-2">
                <Label htmlFor="saved-score">보관함 악보</Label>
                <select
                  id="saved-score"
                  className="flex h-10 w-full rounded-md border border-stone-300 bg-white px-3 text-sm text-stone-900 outline-none ring-offset-white focus-visible:border-stone-400"
                  value={selectedSavedScoreId}
                  onChange={(event) => setSelectedSavedScoreId(event.target.value)}
                >
                  <option value="">악보를 선택하세요</option>
                  {savedScores.map((score) => (
                    <option key={score.score_id} value={score.score_id}>
                      {score.title}
                    </option>
                  ))}
                </select>
              </div>

              {selectedSavedScore ? (
                <div className="rounded-md border border-stone-200 bg-stone-50 p-3 text-sm text-stone-600">
                  최근 주차 {getSavedScoreWeekLabel(selectedSavedScore)} · 사용{" "}
                  {selectedSavedScore.use_count}회
                </div>
              ) : null}

              <div className="space-y-2">
                <Label>주차 선택</Label>
                <DatePicker value={weekOf} onChange={setWeekOf} />
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

              {!isLibraryUpload ? (
                <>
                  <div className="space-y-2">
                    <Label htmlFor="church-name">교회 이름</Label>
                    <Input
                      id="church-name"
                      value={churchName}
                      onChange={(event) => setChurchName(event.target.value)}
                      placeholder="예: 작은샘골 사랑의 교회"
                      required
                    />
                  </div>

                  <div className="space-y-2">
                    <Label>주차 선택</Label>
                    <DatePicker value={weekOf} onChange={setWeekOf} />
                  </div>
                </>
              ) : null}

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

              {isLibraryUpload && previewUrl ? (
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
            </>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="outline" onClick={onClose}>
              취소
            </Button>
            <Button
              type="submit"
              disabled={
                isSubmitting ||
                (mode === "library"
                  ? !selectedSavedScoreId || !weekLabel
                  : !title || !file || (!isLibraryUpload && (!churchName.trim() || !weekLabel)))
              }
            >
              {mode === "library"
                ? applyLoading
                  ? "반영 중..."
                  : "주차 반영"
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
