import { Badge } from "../../../components/ui/badge"
import { Button } from "../../../components/ui/button"
import { Card, CardContent } from "../../../components/ui/card"

export default function HeroSection({ totalSongs, onUpload }) {
  return (
    <Card className="border-stone-200/80 bg-gradient-to-b from-white to-stone-50/40">
      <CardContent className="flex flex-col gap-6 p-6 md:flex-row md:items-end md:justify-between">
        <div className="space-y-3">
          <Badge variant="secondary" className="rounded-full px-3 py-1 text-[11px]">
            이번 주
          </Badge>
          <div className="space-y-1">
            <h1 className="text-2xl font-semibold tracking-tight text-stone-950 md:text-3xl">
              주간 콘티를 빠르게 정리합니다
            </h1>
            <p className="text-sm text-stone-600">점검, 공유, 수정 흐름을 한 화면에서 관리하세요.</p>
          </div>
          <Button type="button" onClick={onUpload}>
            악보 업로드
          </Button>
        </div>
        <div className="grid w-full grid-cols-3 gap-3 md:w-auto">
          <div className="rounded-lg border border-stone-200 bg-white px-4 py-3">
            <p className="text-xs text-stone-500">총 곡 수</p>
            <p className="mt-1 text-lg font-semibold text-stone-950">{totalSongs}</p>
          </div>
          <div className="rounded-lg border border-stone-200 bg-white px-4 py-3">
            <p className="text-xs text-stone-500">상태</p>
            <p className="mt-1 text-lg font-semibold text-stone-950">Draft</p>
          </div>
          <div className="rounded-lg border border-stone-200 bg-white px-4 py-3">
            <p className="text-xs text-stone-500">버전</p>
            <p className="mt-1 text-lg font-semibold text-stone-950">v1</p>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
