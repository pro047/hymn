import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";

export default function WeekSummaryCard({ weekSummaries }) {
  return (
    <Card>
      <CardHeader className="pb-4">
        <CardTitle>다가오는 주차</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* The 대기/초안 badges are gone: both were fixed strings. Score.status
            exists in the database but is written 'draft' once and never read
            back — ScoreResponse does not carry it. A badge that cannot change
            says nothing. */}
        {weekSummaries.length === 0 ? (
          <div className="rounded-md border border-stone-200 p-3">
            <span className="text-sm text-stone-600">등록된 주차가 없습니다.</span>
          </div>
        ) : (
          weekSummaries.map((item) => (
            <div key={item.week_of} className="rounded-md border border-stone-200 p-3">
              <span className="text-sm text-stone-700">
                {item.week_of} - {item.title}
              </span>
            </div>
          ))
        )}
      </CardContent>
    </Card>
  );
}
