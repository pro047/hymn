import { useMemo, useState } from "react"
import { addDays, format, startOfWeek } from "date-fns"

import { Alert, AlertDescription, AlertTitle } from "../components/ui/alert"
import { Button } from "../components/ui/button"
import { Separator } from "../components/ui/separator"
import HeroSection from "../features/home/sections/hero-section"
import RecentScoresCard from "../features/home/sections/recent-scores-card"
import StageCard from "../features/home/sections/stage-card"
import WeekSummaryCard from "../features/home/sections/week-summary-card"
import ScoreUploadDialog from "../features/score/components/score-upload-dialog"
import { useScores } from "../features/score/hooks/use-scores"

const tabs = [
  { id: "scores", label: "악보" },
  { id: "weeks", label: "주차" },
  { id: "uploads", label: "업로드" },
  { id: "settings", label: "설정" },
]

export default function HomePage() {
  const [activeTab, setActiveTab] = useState("scores")
  const [isUploadOpen, setIsUploadOpen] = useState(false)

  const {
    scores,
    weekSummaries,
    error,
    isUploading,
    createScoreWithUpload,
    updateScore,
    deleteScore,
  } = useScores()

  const upcomingSundayWeekOf = useMemo(() => {
    const today = new Date()
    const thisWeekStart = startOfWeek(today, { weekStartsOn: 1 })
    const upcomingSunday = addDays(thisWeekStart, 6)
    return format(upcomingSunday, "yyyy-MM-dd")
  }, [])

  const upcomingSundayScores = useMemo(() => {
    return scores.filter((score) => String(score.week_of).slice(0, 10) === upcomingSundayWeekOf)
  }, [scores, upcomingSundayWeekOf])

  return (
    <div className="min-h-screen bg-white text-stone-900">
      <header className="border-b border-stone-200 bg-white/95 backdrop-blur">
        <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 px-4 py-4 sm:px-6 md:flex-row md:items-center md:justify-between lg:px-8">
          <div className="flex items-start gap-3">
            <div className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-stone-200 bg-stone-900 text-xs font-semibold text-stone-50">
              H
            </div>
            <div className="space-y-0.5">
              <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-stone-500">Hymn Console</p>
              <h1 className="text-base font-semibold tracking-tight text-stone-950">Worship Planner</h1>
            </div>
          </div>
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
        </div>
      </header>

      <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-4 py-8 sm:px-6 lg:px-8">
        <HeroSection totalSongs={scores.length} onUpload={() => setIsUploadOpen(true)} />

        {error ? (
          <Alert variant="destructive">
            <AlertTitle>요청 실패</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : null}

        <main className="space-y-6">
          {activeTab === "scores" ? (
            <>
              <section className="grid gap-4 md:grid-cols-2">
                <WeekSummaryCard weekSummaries={weekSummaries} />
                <RecentScoresCard scores={scores} />
              </section>
              <StageCard
                scores={upcomingSundayScores}
                weekOf={upcomingSundayWeekOf}
                onUpdate={updateScore}
                onDelete={deleteScore}
              />
            </>
          ) : (
            <section className="rounded-xl border border-dashed border-stone-300 bg-white p-8 text-sm text-stone-500">
              준비 중인 탭입니다.
            </section>
          )}
        </main>

        <Separator />
      </div>

      <ScoreUploadDialog
        open={isUploadOpen}
        onClose={() => setIsUploadOpen(false)}
        onSubmit={createScoreWithUpload}
        loading={isUploading}
      />
    </div>
  )
}
