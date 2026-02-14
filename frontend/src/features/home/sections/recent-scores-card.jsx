import { Badge } from "../../../components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card"

export default function RecentScoresCard({ scores }) {
  const recentScores = scores.slice(0, 3)

  return (
    <Card>
      <CardHeader className="pb-4">
        <CardTitle>최근 악보</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {recentScores.length === 0 ? (
          <div className="flex items-center justify-between rounded-md border border-stone-200 p-3">
            <span className="text-sm text-stone-600">등록된 악보가 없습니다.</span>
            <Badge variant="secondary">대기</Badge>
          </div>
        ) : (
          recentScores.map((score) => (
            <div
              key={score.id}
              className="flex items-center justify-between rounded-md border border-stone-200 p-3"
            >
              <span className="text-sm text-stone-700">{score.title}</span>
              <Badge variant="outline">등록</Badge>
            </div>
          ))
        )}
      </CardContent>
    </Card>
  )
}
