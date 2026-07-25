import { useRef } from "react"
import { Trash2 } from "lucide-react"

import { Button } from "../../../components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card"

export default function SavedScoresCard({
  scores,
  onApplyRequest,
  onRemove,
  onQuickUpload,
  pendingSaveScoreId,
}) {
  const fileInputRef = useRef(null)

  const handleFileChange = (event) => {
    const selectedFile = event.target.files?.[0] || null
    if (selectedFile) {
      onQuickUpload?.(selectedFile)
    }
    event.target.value = ""
  }

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <div>
          <CardTitle>악보 보관함</CardTitle>
          <p className="mt-1 text-xs text-stone-500">저장한 악보를 여러 주차에 다시 반영하거나 새 이미지를 바로 추가합니다.</p>
        </div>
        <div className="flex items-center gap-2">
          <input
            ref={fileInputRef}
            className="hidden"
            type="file"
            accept="image/*"
            onChange={handleFileChange}
          />
          <Button type="button" size="sm" onClick={() => fileInputRef.current?.click()}>
            업로드
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {scores.length === 0 ? (
          <div className="rounded-md border border-dashed border-stone-300 p-4 text-sm text-stone-500">
            저장한 악보가 없습니다.
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-5">
            {scores.map((score) => (
              <div key={score.score_id} className="group relative min-w-0">
                <button
                  type="button"
                  className="block w-full text-left"
                  onClick={() => onApplyRequest(score)}
                >
                  <div className="overflow-hidden rounded-xl border border-stone-200 bg-stone-50 shadow-sm transition group-hover:border-stone-300 group-hover:shadow-md">
                    <div className="aspect-square overflow-hidden bg-stone-100">
                      <img
                        src={score.download_url ?? score.file_url}
                        alt={score.title}
                        className="h-full w-full object-cover transition duration-200 group-hover:scale-[1.02]"
                      />
                    </div>
                    <div className="border-t border-stone-200 bg-white px-3 py-2">
                      <p className="truncate text-sm font-medium text-stone-900">{score.title}</p>
                    </div>
                  </div>
                </button>
                <Button
                  variant="outline"
                  size="icon"
                  type="button"
                  className="absolute right-2 top-2 h-8 w-8 rounded-full border-stone-200 bg-white/95 opacity-0 shadow-sm transition group-hover:opacity-100"
                  disabled={pendingSaveScoreId === score.score_id}
                  onClick={(event) => {
                    event.stopPropagation()
                    onRemove(score.score_id)
                  }}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
