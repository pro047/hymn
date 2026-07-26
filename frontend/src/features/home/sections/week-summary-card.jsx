import { Badge } from "../../../components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";

export default function WeekSummaryCard({ weekSummaries }) {
  return (
    <Card>
      <CardHeader className="pb-4">
        <CardTitle>다가오는 주차</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {weekSummaries.length === 0 ? (
          <div className="flex items-center justify-between rounded-md border border-stone-200 p-3">
            <span className="text-sm text-stone-600">등록된 주차가 없습니다.</span>
            <Badge variant="secondary">대기</Badge>
          </div>
        ) : (
          weekSummaries.map((item) => (
            <div
              key={item.week_of}
              className="flex items-center justify-between rounded-md border border-stone-200 p-3"
            >
              <span className="text-sm text-stone-700">
                {item.week_of} - {item.title}
              </span>
              <Badge variant="outline">초안</Badge>
            </div>
          ))
        )}
      </CardContent>
    </Card>
  );
}
