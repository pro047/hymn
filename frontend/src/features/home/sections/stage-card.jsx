import { Button } from "../../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";

export default function StageCard({
  scores,
  weekOf,
  onUpdate,
  onDelete,
  savedScoreIds,
  pendingSaveScoreId,
  onToggleSave,
}) {
  const stageScores = scores.slice(0, 5);

  return (
    <Card>
      {/* No 섞기/발행 here. Both were buttons with no onClick — reordering has
          no API (SetItem.order_no is only rewritten when week_of changes) and
          publishing has no transition (status is written 'draft' at creation,
          never changed, and not even carried in ScoreResponse). Put them back
          when the endpoints exist, not before. */}
      <CardHeader>
        <CardTitle>콘티</CardTitle>
        <p className="mt-1 text-xs text-stone-500">{weekOf} (돌아오는 일요일)</p>
      </CardHeader>
      <CardContent className="space-y-2">
        {stageScores.length === 0 ? (
          <div className="rounded-md border border-dashed border-stone-300 p-4 text-sm text-stone-500">
            돌아오는 일요일 주차의 악보가 없습니다.
          </div>
        ) : (
          stageScores.map((score, index) => (
            <div
              key={score.id}
              className="grid grid-cols-[auto_1fr_auto] items-center gap-3 rounded-md border border-stone-200 p-3"
            >
              <span className="inline-flex h-7 w-7 items-center justify-center rounded-md bg-stone-100 text-xs font-semibold text-stone-700">
                {index + 1}
              </span>
              <button
                type="button"
                className="truncate text-left text-sm font-medium text-stone-900"
                onClick={() => onUpdate(score)}
              >
                {score.title}
              </button>
              <div className="flex items-center gap-1">
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
                <Button variant="ghost" size="sm" type="button" onClick={() => onUpdate(score)}>
                  수정
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  type="button"
                  className="text-red-600 hover:bg-red-50 hover:text-red-700"
                  onClick={() => onDelete(score.id)}
                >
                  삭제
                </Button>
              </div>
            </div>
          ))
        )}
      </CardContent>
    </Card>
  );
}
