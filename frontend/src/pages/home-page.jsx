import { useMemo, useState } from "react";

import { Alert, AlertDescription, AlertTitle } from "../components/ui/alert";
import { Button } from "../components/ui/button";
import { Separator } from "../components/ui/separator";
import { useUpcomingSunday } from "../features/home/hooks/use-upcoming-sunday";
import HeroSection from "../features/home/sections/hero-section";
import StageCard from "../features/home/sections/stage-card";
import SavedScoresCard from "../features/score/components/saved-scores-card";
import ScoreEditDialog from "../features/score/components/score-edit-dialog";
import ScoreUploadDialog from "../features/score/components/score-upload-dialog";
import { useScores } from "../features/score/hooks/use-scores";

// 주차·설정 are gone: both rendered "준비 중인 탭입니다" and nothing else.
const tabs = [
  { id: "scores", label: "악보" },
  { id: "library", label: "보관함" },
];

// headerActions is a slot, not a role flag: who may see 교회 관리 and what
// 로그아웃 does are session concerns, and App already answers both. This page
// only decides where the group sits.
export default function HomePage({ headerActions = null }) {
  const [activeTab, setActiveTab] = useState("scores");
  const [uploadDialogState, setUploadDialogState] = useState({
    open: false,
    mode: null,
    file: null,
    savedScore: null,
    lockMode: false,
    saveToLibrary: false,
    sessionKey: 0,
  });
  const [editingScore, setEditingScore] = useState(null);

  const {
    scores,
    totalSongs,
    savedScores,
    savedSongIds,
    error,
    isUploading,
    isUpdating,
    pendingSaveSongId,
    isApplyingSavedScore,
    createScoreWithUpload,
    updateScore,
    deleteScore,
    toggleSavedScore,
    removeSavedScore,
    applySavedScoreToWeek,
  } = useScores();

  const upcomingSundayWeekOf = useUpcomingSunday();

  const upcomingSundayScores = useMemo(() => {
    return scores.filter((score) => String(score.week_of).slice(0, 10) === upcomingSundayWeekOf);
  }, [scores, upcomingSundayWeekOf]);

  const openUploadDialog = ({
    mode = null,
    file = null,
    savedScore = null,
    lockMode = false,
    saveToLibrary = false,
  } = {}) => {
    setUploadDialogState({
      open: true,
      mode,
      file,
      savedScore,
      lockMode,
      saveToLibrary,
      sessionKey: Date.now(),
    });
  };

  const closeUploadDialog = () => {
    setUploadDialogState({
      open: false,
      mode: null,
      file: null,
      savedScore: null,
      lockMode: false,
      saveToLibrary: false,
      sessionKey: 0,
    });
  };

  return (
    <div className="min-h-screen bg-white text-stone-900">
      <header className="border-b border-stone-200 bg-white/95 backdrop-blur">
        <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 px-4 py-4 sm:px-6 md:flex-row md:items-center md:justify-between lg:px-8">
          <div className="flex items-start gap-3">
            <div className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-stone-200 bg-stone-900 text-xs font-semibold text-stone-50">
              H
            </div>
            <div className="space-y-0.5">
              <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-stone-500">
                Hymn Console
              </p>
              <h1 className="text-base font-semibold tracking-tight text-stone-950">
                Worship Planner
              </h1>
            </div>
          </div>
          {tabs.length > 1 || headerActions ? (
            // Two groups, one row. The outer gap is wider than the inner one so
            // navigating the page and leaving it do not read as one button row.
            <div className="flex flex-wrap items-center gap-4">
              {tabs.length > 1 ? (
                <div className="flex flex-wrap items-center gap-2">
                  {tabs.map((tab) => (
                    <Button
                      key={tab.id}
                      type="button"
                      size="sm"
                      variant={activeTab === tab.id ? "default" : "ghost"}
                      onClick={() => setActiveTab(tab.id)}
                    >
                      {tab.label}
                    </Button>
                  ))}
                </div>
              ) : null}
              {headerActions}
            </div>
          ) : null}
        </div>
      </header>

      <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-4 py-8 sm:px-6 lg:px-8">
        <HeroSection totalSongs={totalSongs} onUpload={() => openUploadDialog()} />

        {error ? (
          <Alert variant="destructive">
            <AlertTitle>요청 실패</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : null}

        <main className="space-y-6">
          {activeTab === "scores" ? (
            /* 다가오는 주차·최근 악보 cards are gone. Both sliced the first
               three of a list the server sorts by created_at ASC, so they
               showed the oldest rows under names promising the newest. Fixing
               the sort would not have earned them back: no week is ever
               uploaded ahead of the coming Sunday (30 weeks, 5 songs each, none
               past it), so a corrected 다가오는 주차 has exactly one week to
               show — the one 콘티 already shows — and 최근 악보 becomes a subset
               of it. */
            <StageCard
              scores={upcomingSundayScores}
              weekOf={upcomingSundayWeekOf}
              onUpdate={setEditingScore}
              onDelete={deleteScore}
              savedSongIds={savedSongIds}
              pendingSaveSongId={pendingSaveSongId}
              onToggleSave={toggleSavedScore}
            />
          ) : (
            <SavedScoresCard
              scores={savedScores}
              onApplyRequest={(score) => openUploadDialog({ mode: "library", savedScore: score })}
              onQuickUpload={(file) =>
                openUploadDialog({
                  mode: "pc",
                  file,
                  lockMode: true,
                  saveToLibrary: true,
                })
              }
              onRemove={removeSavedScore}
              pendingSaveSongId={pendingSaveSongId}
            />
          )}
        </main>

        <Separator />
      </div>

      {/* Keyed on the score so picking a different row remounts the form
          instead of carrying the previous title and file selection over. */}
      <ScoreEditDialog
        key={editingScore?.id ?? "none"}
        open={Boolean(editingScore)}
        score={editingScore}
        onClose={() => setEditingScore(null)}
        onSubmit={updateScore}
        loading={isUpdating}
      />

      <ScoreUploadDialog
        key={uploadDialogState.sessionKey}
        open={uploadDialogState.open}
        onClose={closeUploadDialog}
        onUploadSubmit={createScoreWithUpload}
        onApplySavedScore={applySavedScoreToWeek}
        savedScores={savedScores}
        uploadLoading={isUploading}
        applyLoading={isApplyingSavedScore}
        initialMode={uploadDialogState.mode}
        initialFile={uploadDialogState.file}
        initialSavedScore={uploadDialogState.savedScore}
        lockMode={uploadDialogState.lockMode}
        saveToLibrary={uploadDialogState.saveToLibrary}
      />
    </div>
  );
}
