import { useMemo, useState } from "react"
import { format } from "date-fns"

import DatePicker from "../../../components/DatePicker"
import { Button } from "../../../components/ui/button"
import { Input } from "../../../components/ui/input"
import { Label } from "../../../components/ui/label"

export default function ScoreUploadDialog({ open, onClose, onSubmit, loading }) {
  const [title, setTitle] = useState("")
  const [churchName, setChurchName] = useState("")
  const [weekOf, setWeekOf] = useState(null)
  const [file, setFile] = useState(null)

  const weekLabel = useMemo(() => {
    if (!weekOf) return ""
    return format(weekOf, "yyyy-MM-dd")
  }, [weekOf])

  if (!open) return null

  const handleSubmit = async (event) => {
    event.preventDefault()
    const normalizedChurchName = churchName.replace(/\s+/g, "")
    if (!title || !normalizedChurchName || !weekOf || !file) return
    const result = await onSubmit({
      title,
      churchName: normalizedChurchName,
      weekOf: weekLabel,
      file,
    })

    if (result?.ok) {
      setTitle("")
      setChurchName("")
      setWeekOf(null)
      setFile(null)
      onClose()
      window.alert("업로드가 완료되었습니다.")
    }
  }

  return (
    <div className="fixed inset-0 z-50 bg-stone-950/40 px-4 py-10 backdrop-blur-sm">
      <div className="mx-auto w-full max-w-xl rounded-2xl border border-stone-200 bg-white p-6 shadow-xl">
        <div className="mb-6 flex items-start justify-between gap-4">
          <div>
            <p className="text-xs font-medium uppercase tracking-[0.12em] text-stone-500">악보 업로드</p>
            <h2 className="mt-1 text-xl font-semibold text-stone-950">새 악보를 등록하세요</h2>
          </div>
          <Button type="button" variant="ghost" size="sm" onClick={onClose}>
            닫기
          </Button>
        </div>

        <form className="space-y-4" onSubmit={handleSubmit}>
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

          <div className="space-y-2">
            <Label htmlFor="score-file">이미지 파일</Label>
            <Input
              id="score-file"
              type="file"
              accept="image/*"
              onChange={(event) => setFile(event.target.files?.[0] || null)}
              required
            />
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="outline" onClick={onClose}>
              취소
            </Button>
            <Button type="submit" disabled={loading}>
              {loading ? "업로드 중..." : "업로드"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}
