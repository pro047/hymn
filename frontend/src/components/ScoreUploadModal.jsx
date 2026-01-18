import { useMemo, useState } from "react"
import { format } from "date-fns"

import DatePicker from "./DatePicker"

export default function ScoreUploadModal({ open, onClose, onSubmit, loading }) {
  const [title, setTitle] = useState("")
  const [churchId, setChurchId] = useState("church-uuid")
  const [weekOf, setWeekOf] = useState(null)
  const [file, setFile] = useState(null)

  const weekLabel = useMemo(() => {
    if (!weekOf) return ""
    return format(weekOf, "yyyy-MM-dd")
  }, [weekOf])

  if (!open) return null

  const handleSubmit = (event) => {
    event.preventDefault()
    if (!title || !churchId || !weekOf || !file) return
    onSubmit({
      title,
      churchId,
      weekOf: weekLabel,
      file,
    })
  }

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true">
      <div className="modal">
        <div className="modal-header">
          <div>
            <p className="modal-kicker">악보 업로드</p>
            <h3>새 악보를 등록하세요</h3>
          </div>
          <button type="button" className="modal-close" onClick={onClose}>
            닫기
          </button>
        </div>

        <form className="modal-body" onSubmit={handleSubmit}>
          <label className="field">
            <span>악보 제목</span>
            <input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="예: 믿음의 고백"
              required
            />
          </label>

          <label className="field">
            <span>교회 ID</span>
            <input
              value={churchId}
              onChange={(event) => setChurchId(event.target.value)}
              placeholder="church-uuid"
              required
            />
          </label>

          <label className="field">
            <span>주차 선택</span>
            <DatePicker value={weekOf} onChange={setWeekOf} />
          </label>

          <label className="field">
            <span>이미지 파일</span>
            <input
              type="file"
              accept="image/*"
              onChange={(event) => setFile(event.target.files?.[0] || null)}
              required
            />
          </label>

          <div className="modal-actions">
            <button type="button" className="ghost-button" onClick={onClose}>
              취소
            </button>
            <button type="submit" className="primary-button" disabled={loading}>
              {loading ? "업로드 중..." : "업로드"}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
