import { useCallback, useEffect, useMemo, useState } from "react";

import { apiFetch } from "../../../api/client";
import { API_PATHS } from "../../../api/paths";
import { isAuthenticated } from "../../../lib/auth-storage";
import { SAVED_SCORES_ENABLED } from "../feature-flags";

export function useScores() {
  const [scores, setScores] = useState([]);
  const [savedScores, setSavedScores] = useState([]);
  const [error, setError] = useState("");
  const [isUploading, setIsUploading] = useState(false);
  const [isUpdating, setIsUpdating] = useState(false);
  const [pendingSaveScoreId, setPendingSaveScoreId] = useState(null);
  const [isApplyingSavedScore, setIsApplyingSavedScore] = useState(false);

  const savedScoreIds = useMemo(
    () => new Set(savedScores.map((score) => score.score_id)),
    [savedScores]
  );

  const fetchScores = useCallback(async () => {
    try {
      const response = await fetch(API_PATHS.scores);
      if (!response.ok) {
        throw new Error("악보 목록을 불러오지 못했습니다.");
      }
      const data = await response.json();
      setScores(data);
      setError("");
    } catch (err) {
      setError(err.message);
    }
  }, []);

  const fetchSavedScores = useCallback(async () => {
    // Nothing renders saved scores while the flag is off, so this request only
    // cost a round trip on every mount and threw its answer away.
    if (!SAVED_SCORES_ENABLED || !isAuthenticated()) {
      setSavedScores([]);
      return;
    }
    try {
      const response = await apiFetch(API_PATHS.savedScores);
      if (!response.ok) {
        throw new Error("저장소 목록을 불러오지 못했습니다.");
      }
      const data = await response.json();
      setSavedScores(data);
      setError("");
    } catch (err) {
      setError(err.message);
    }
  }, []);

  useEffect(() => {
    fetchScores();
    fetchSavedScores();
  }, [fetchSavedScores, fetchScores]);

  const createScoreWithUpload = async ({ title, weekOf, file, saveToLibrary = false }) => {
    // Both branches write now, so the check no longer depends on saveToLibrary.
    if (!isAuthenticated()) {
      setError("로그인이 필요합니다.");
      return { ok: false };
    }

    setIsUploading(true);
    try {
      // Decide the whole request shape once, instead of branching per field.
      const { request, url, payload } = saveToLibrary
        ? {
            request: apiFetch,
            url: API_PATHS.savedScoreUpload,
            payload: { title, filename: file.name, content_type: file.type },
          }
        : {
            // apiFetch, not fetch: /scores writes require a token now, and the
            // church comes from it rather than from a field in this payload.
            request: apiFetch,
            url: API_PATHS.scores,
            payload: {
              title,
              week_of: weekOf,
              storage_type: "s3",
              filename: file.name,
              content_type: file.type,
            },
          };
      const response = await request(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        throw new Error("악보 생성에 실패했습니다.");
      }

      const data = await response.json();
      const uploadResponse = await fetch(data.upload_url, {
        method: "PUT",
        headers: { "Content-Type": file.type || "application/octet-stream" },
        body: file,
      });

      if (!uploadResponse.ok) {
        throw new Error("S3 업로드에 실패했습니다.");
      }

      await Promise.all([fetchScores(), saveToLibrary ? fetchSavedScores() : Promise.resolve()]);
      return { ok: true, scoreId: data.score_id };
    } catch (err) {
      setError(err.message);
      return { ok: false };
    } finally {
      setIsUploading(false);
    }
  };

  const uploadReplacementFile = async (scoreId, file) => {
    const issued = await apiFetch(API_PATHS.scoreFile(scoreId), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename: file.name, content_type: file.type }),
    });
    if (!issued.ok) {
      throw new Error("업로드 주소를 받지 못했습니다.");
    }
    const { upload_url: uploadUrl, s3_key: s3Key } = await issued.json();
    const uploaded = await fetch(uploadUrl, {
      method: "PUT",
      headers: { "Content-Type": file.type || "application/octet-stream" },
      body: file,
    });
    if (!uploaded.ok) {
      throw new Error("S3 업로드에 실패했습니다.");
    }
    return s3Key;
  };

  const updateScore = async ({ scoreId, title, file = null }) => {
    if (!isAuthenticated()) {
      setError("로그인이 필요합니다.");
      return { ok: false };
    }
    // The column is varchar(255) and the server answers 422 past it. The dialog
    // caps the field too; this stays because the message is readable and the
    // 422 body is not.
    if (title.length > 255) {
      const message = "제목은 255자 이내로 입력해주세요.";
      setError(message);
      return { ok: false, message };
    }

    setIsUpdating(true);
    try {
      // Upload first, PATCH second. Reversed, a failed PUT would leave the row
      // pointing at an object that was never written — a broken image on the
      // page. This way the score keeps the file it already had.
      const fileUri = file ? await uploadReplacementFile(scoreId, file) : null;
      const response = await apiFetch(API_PATHS.score(scoreId), {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(fileUri ? { title, file_uri: fileUri } : { title }),
      });
      if (!response.ok) {
        throw new Error("악보 수정에 실패했습니다.");
      }
      await fetchScores();
      return { ok: true };
    } catch (err) {
      // Returned as well as pushed to `error`, because the page's alert renders
      // behind the dialog's own fixed backdrop — the caller has to show this
      // itself or the user sees the button stop spinning and nothing else.
      setError(err.message);
      return { ok: false, message: err.message };
    } finally {
      setIsUpdating(false);
    }
  };

  const deleteScore = async (scoreId) => {
    const confirmed = window.confirm("정말 삭제할까요?");
    if (!confirmed) return;
    try {
      const response = await apiFetch(API_PATHS.score(scoreId), {
        method: "DELETE",
      });
      if (!response.ok) {
        throw new Error("악보 삭제에 실패했습니다.");
      }
      await fetchScores();
    } catch (err) {
      setError(err.message);
    }
  };

  const saveScore = async (scoreId) => {
    if (!isAuthenticated()) {
      setError("로그인이 필요합니다.");
      return;
    }
    setPendingSaveScoreId(scoreId);
    try {
      const response = await apiFetch(API_PATHS.savedScore(scoreId), {
        method: "POST",
      });
      if (!response.ok) {
        throw new Error("악보 저장에 실패했습니다.");
      }
      await fetchSavedScores();
    } catch (err) {
      setError(err.message);
    } finally {
      setPendingSaveScoreId(null);
    }
  };

  const removeSavedScore = async (scoreId) => {
    if (!isAuthenticated()) {
      setError("로그인이 필요합니다.");
      return;
    }
    setPendingSaveScoreId(scoreId);
    try {
      const response = await apiFetch(API_PATHS.savedScore(scoreId), {
        method: "DELETE",
      });
      if (!response.ok) {
        throw new Error("저장소 삭제에 실패했습니다.");
      }
      await fetchSavedScores();
    } catch (err) {
      setError(err.message);
    } finally {
      setPendingSaveScoreId(null);
    }
  };

  const toggleSavedScore = async (scoreId) => {
    if (savedScoreIds.has(scoreId)) {
      await removeSavedScore(scoreId);
      return;
    }
    await saveScore(scoreId);
  };

  const applySavedScoreToWeek = async ({ scoreId, weekOf }) => {
    if (!isAuthenticated()) {
      setError("로그인이 필요합니다.");
      return { ok: false };
    }
    setIsApplyingSavedScore(true);
    try {
      const response = await apiFetch(API_PATHS.applySavedScore(scoreId), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ week_of: weekOf }),
      });
      if (!response.ok) {
        throw new Error("저장소 악보를 주차에 반영하지 못했습니다.");
      }
      await Promise.all([fetchScores(), fetchSavedScores()]);
      return { ok: true };
    } catch (err) {
      setError(err.message);
      return { ok: false };
    } finally {
      setIsApplyingSavedScore(false);
    }
  };

  return {
    scores,
    savedScores,
    savedScoreIds,
    error,
    isUploading,
    isUpdating,
    pendingSaveScoreId,
    isApplyingSavedScore,
    createScoreWithUpload,
    updateScore,
    deleteScore,
    saveScore,
    removeSavedScore,
    toggleSavedScore,
    applySavedScoreToWeek,
  };
}
