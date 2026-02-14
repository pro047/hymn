import { useCallback, useEffect, useMemo, useState } from "react"

import { API_PATHS } from "../../../api/paths"

export function useScores() {
  const [scores, setScores] = useState([])
  const [error, setError] = useState("")
  const [isUploading, setIsUploading] = useState(false)

  const weekSummaries = useMemo(() => {
    const uniqueWeeks = new Map()
    scores.forEach((score) => {
      if (!uniqueWeeks.has(score.week_of)) {
        uniqueWeeks.set(score.week_of, score)
      }
    })
    return Array.from(uniqueWeeks.values()).slice(0, 3)
  }, [scores])

  const fetchScores = useCallback(async () => {
    try {
      const response = await fetch(API_PATHS.scores)
      if (!response.ok) {
        throw new Error("악보 목록을 불러오지 못했습니다.")
      }
      const data = await response.json()
      setScores(data)
      setError("")
    } catch (err) {
      setError(err.message)
    }
  }, [])

  useEffect(() => {
    fetchScores()
  }, [fetchScores])

  const createScoreWithUpload = async ({ title, churchName, weekOf, file }) => {
    setIsUploading(true)
    try {
      const response = await fetch(API_PATHS.scores, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title,
          church_name: churchName,
          week_of: weekOf,
          storage_type: "s3",
          filename: file.name,
          content_type: file.type,
        }),
      })

      if (!response.ok) {
        throw new Error("악보 생성에 실패했습니다.")
      }

      const data = await response.json()
      const uploadResponse = await fetch(data.upload_url, {
        method: "PUT",
        headers: { "Content-Type": file.type || "application/octet-stream" },
        body: file,
      })

      if (!uploadResponse.ok) {
        throw new Error("S3 업로드에 실패했습니다.")
      }

      await fetchScores()
      return { ok: true }
    } catch (err) {
      setError(err.message)
      return { ok: false }
    } finally {
      setIsUploading(false)
    }
  }

  const updateScore = async (scoreId) => {
    const title = window.prompt("새 제목을 입력하세요.")
    if (!title) return
    try {
      const response = await fetch(API_PATHS.score(scoreId), {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
      })
      if (!response.ok) {
        throw new Error("악보 수정에 실패했습니다.")
      }
      await fetchScores()
    } catch (err) {
      setError(err.message)
    }
  }

  const deleteScore = async (scoreId) => {
    const confirmed = window.confirm("정말 삭제할까요?")
    if (!confirmed) return
    try {
      const response = await fetch(API_PATHS.score(scoreId), {
        method: "DELETE",
      })
      if (!response.ok) {
        throw new Error("악보 삭제에 실패했습니다.")
      }
      await fetchScores()
    } catch (err) {
      setError(err.message)
    }
  }

  return {
    scores,
    weekSummaries,
    error,
    isUploading,
    createScoreWithUpload,
    updateScore,
    deleteScore,
  }
}
