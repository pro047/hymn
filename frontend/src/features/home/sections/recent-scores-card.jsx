import { Button } from "../../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";

export default function RecentScoresCard({
  scores,
  savedScoreIds,
  pendingSaveScoreId,
  onToggleSave,
}) {
  const recentScores = scores.slice(0, 3);

  return (
    <Card>
      <CardHeader className="pb-4">
        <CardTitle>최근 악보</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* 대기/등록 badges removed — see week-summary-card for why. */}
        {recentScores.length === 0 ? (
          <div className="rounded-md border border-stone-200 p-3">
            <span className="text-sm text-stone-600">등록된 악보가 없습니다.</span>
          </div>
        ) : (
          recentScores.map((score) => (
            <div
              key={score.id}
              className="flex items-center justify-between rounded-md border border-stone-200 p-3"
            >
              <div className="min-w-0 pr-3">
                <span className="block truncate text-sm text-stone-700">{score.title}</span>
              </div>
              <div className="flex items-center gap-2">
                {onToggleSave ? (
                  <Button
                    variant="ghost"
                    size="sm"
                    type="button"
                    disabled={pendingSaveScoreId === score.id}
                    onClick={() => onToggleSave(score.id)}
                  >
                    {savedScoreIds.has(score.id) ? "저장 해제" : "저장"}
                  </Button>
                ) : null}
              </div>
            </div>
          ))
        )}
      </CardContent>
    </Card>
  );
}
