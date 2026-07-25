import { useCallback, useEffect, useMemo, useState } from "react"

import { API_PATHS } from "../../../api/paths"

function getAuthHeaders() {
  const token = localStorage.getItem("hymn_access_token")
  return token ? { Authorization: `Bearer ${token}` } : {}
}

function hasAccessToken() {
  return Boolean(localStorage.getItem("hymn_access_token"))
}

export function useScores() {
  const [scores, setScores] = useState([])
  const [savedScores, setSavedScores] = useState([])
  const [error, setError] = useState("")
  const [isUploading, setIsUploading] = useState(false)
  const [pendingSaveScoreId, setPendingSaveScoreId] = useState(null)
  const [isApplyingSavedScore, setIsApplyingSavedScore] = useState(false)

  const weekSummaries = useMemo(() => {
    const uniqueWeeks = new Map()
    scores.forEach((score) => {
      if (!uniqueWeeks.has(score.week_of)) {
        uniqueWeeks.set(score.week_of, score)
      }
    })
    return Array.from(uniqueWeeks.values()).slice(0, 3)
  }, [scores])

  const savedScoreIds = useMemo(() => new Set(savedScores.map((score) => score.score_id)), [savedScores])

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

  const fetchSavedScores = useCallback(async () => {
    if (!hasAccessToken()) {
      setSavedScores([])
      return
    }
    try {
      const response = await fetch(API_PATHS.savedScores, {
        headers: getAuthHeaders(),
      })
      if (!response.ok) {
        throw new Error("저장소 목록을 불러오지 못했습니다.")
      }
      const data = await response.json()
      setSavedScores(data)
      setError("")
    } catch (err) {
      setError(err.message)
    }
  }, [])

  useEffect(() => {
    fetchScores()
    fetchSavedScores()
  }, [fetchSavedScores, fetchScores])

  const createScoreWithUpload = async ({ title, churchName, weekOf, file, saveToLibrary = false }) => {
    if (saveToLibrary && !hasAccessToken()) {
      setError("로그인이 필요합니다.")
      return { ok: false }
    }

    setIsUploading(true)
    try {
      const response = await fetch(saveToLibrary ? API_PATHS.savedScoreUpload : API_PATHS.scores, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(saveToLibrary ? getAuthHeaders() : {}),
        },
        body: JSON.stringify(
          saveToLibrary
            ? {
                title,
                filename: file.name,
                content_type: file.type,
              }
            : {
                title,
                church_name: churchName,
                week_of: weekOf,
                storage_type: "s3",
                filename: file.name,
                content_type: file.type,
              },
        ),
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

      await Promise.all([fetchScores(), saveToLibrary ? fetchSavedScores() : Promise.resolve()])
      return { ok: true, scoreId: data.score_id }
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

  const saveScore = async (scoreId) => {
    if (!hasAccessToken()) {
      setError("로그인이 필요합니다.")
      return
    }
    setPendingSaveScoreId(scoreId)
    try {
      const response = await fetch(API_PATHS.savedScore(scoreId), {
        method: "POST",
        headers: getAuthHeaders(),
      })
      if (!response.ok) {
        throw new Error("악보 저장에 실패했습니다.")
      }
      await fetchSavedScores()
    } catch (err) {
      setError(err.message)
    } finally {
      setPendingSaveScoreId(null)
    }
  }

  const removeSavedScore = async (scoreId) => {
    if (!hasAccessToken()) {
      setError("로그인이 필요합니다.")
      return
    }
    setPendingSaveScoreId(scoreId)
    try {
      const response = await fetch(API_PATHS.savedScore(scoreId), {
        method: "DELETE",
        headers: getAuthHeaders(),
      })
      if (!response.ok) {
        throw new Error("저장소 삭제에 실패했습니다.")
      }
      await fetchSavedScores()
    } catch (err) {
      setError(err.message)
    } finally {
      setPendingSaveScoreId(null)
    }
  }

  const toggleSavedScore = async (scoreId) => {
    if (savedScoreIds.has(scoreId)) {
      await removeSavedScore(scoreId)
      return
    }
    await saveScore(scoreId)
  }

  const applySavedScoreToWeek = async ({ scoreId, weekOf }) => {
    if (!hasAccessToken()) {
      setError("로그인이 필요합니다.")
      return { ok: false }
    }
    setIsApplyingSavedScore(true)
    try {
      const response = await fetch(API_PATHS.applySavedScore(scoreId), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...getAuthHeaders(),
        },
        body: JSON.stringify({ week_of: weekOf }),
      })
      if (!response.ok) {
        throw new Error("저장소 악보를 주차에 반영하지 못했습니다.")
      }
      await Promise.all([fetchScores(), fetchSavedScores()])
      return { ok: true }
    } catch (err) {
      setError(err.message)
      return { ok: false }
    } finally {
      setIsApplyingSavedScore(false)
    }
  }

  return {
    scores,
    savedScores,
    savedScoreIds,
    weekSummaries,
    error,
    isUploading,
    pendingSaveScoreId,
    isApplyingSavedScore,
    createScoreWithUpload,
    updateScore,
    deleteScore,
    saveScore,
    removeSavedScore,
    toggleSavedScore,
    applySavedScoreToWeek,
  }
}
