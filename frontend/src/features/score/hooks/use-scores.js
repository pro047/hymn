import { useCallback, useEffect, useMemo, useState } from "react";

import { apiFetch } from "../../../api/client";
import { API_PATHS } from "../../../api/paths";
import { alertMessageOf, readApiError } from "../../../lib/api-error";
import { isAuthenticated } from "../../../lib/auth-storage";

export function useScores() {
  const [scores, setScores] = useState([]);
  const [librarySongs, setLibrarySongs] = useState([]);
  const [error, setError] = useState("");
  const [isUploading, setIsUploading] = useState(false);
  const [isUpdating, setIsUpdating] = useState(false);
  const [isPlacingSong, setIsPlacingSong] = useState(false);

  // Falls back to title when song_id is absent so a frontend deployed ahead
  // of the migration still shows a meaningful count instead of 0.
  const totalSongs = useMemo(
    () => new Set(scores.map((score) => score.song_id ?? score.title)).size,
    [scores]
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

  const fetchLibrary = useCallback(async () => {
    if (!isAuthenticated()) {
      setLibrarySongs([]);
      return;
    }
    try {
      const response = await apiFetch(API_PATHS.songs);
      if (!response.ok) {
        throw new Error("보관함 목록을 불러오지 못했습니다.");
      }
      const data = await response.json();
      setLibrarySongs(data);
      setError("");
    } catch (err) {
      setError(err.message);
    }
  }, []);

  useEffect(() => {
    fetchScores();
    fetchLibrary();
  }, [fetchLibrary, fetchScores]);

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
            url: API_PATHS.songs,
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
        // D5-a's same-week 409 and the library's same-title 409 both carry a
        // Korean detail the user needs to see; the generic message hid it.
        // Read through api-error because a 422's `detail` is an array of items,
        // not a string: passing it to Error() renders "[object Object]" on
        // screen. Unlike updateScore, this path has no client-side length guard,
        // so an over-long title reaches the server and comes back as a 422.
        // `[]` and not omitted: the dialog renders no inline field errors, so
        // every message has to be promoted to the alert or it is never seen.
        const apiError = await readApiError(response, "악보 생성에 실패했습니다.", []);
        throw new Error(alertMessageOf(apiError));
      }

      const data = await response.json();

      // D5: a reused song's create response has upload_url=null — there is no
      // file to PUT, and fetch(null, ...) would throw if this ran anyway.
      // Scoped to saveToLibrary === false because the library answers a
      // same-titled upload with 409, which is already caught above.
      if (!saveToLibrary && data.reused_song) {
        await fetchScores();
        return { ok: true, scoreId: data.score_id, reused: true };
      }

      const uploadResponse = await fetch(data.upload_url, {
        method: "PUT",
        headers: { "Content-Type": file.type || "application/octet-stream" },
        body: file,
      });

      if (!uploadResponse.ok) {
        throw new Error("S3 업로드에 실패했습니다.");
      }

      // Either way the library changes: a new song, or a known one used again.
      await Promise.all([fetchScores(), fetchLibrary()]);
      // A library upload files no Sunday, so it answers with the song instead.
      return saveToLibrary
        ? { ok: true, songId: data.song_id }
        : { ok: true, scoreId: data.score_id };
    } catch (err) {
      setError(err.message);
      return { ok: false, message: err.message };
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
        // D8's title-collision 409 carries a Korean detail (rename_song's
        // message); the generic message here used to swallow it. Same array-vs
        // -string reason as createScoreWithUpload — the guard above only covers
        // `title`, so a 422 can still arrive from another field.
        const apiError = await readApiError(response, "악보 수정에 실패했습니다.", []);
        throw new Error(alertMessageOf(apiError));
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

  const placeSongOnWeek = async ({ songId, weekOf }) => {
    if (!isAuthenticated()) {
      setError("로그인이 필요합니다.");
      return { ok: false };
    }
    setIsPlacingSong(true);
    try {
      const response = await apiFetch(API_PATHS.songUsages(songId), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ week_of: weekOf }),
      });
      if (!response.ok) {
        // The week-clash 409 carries a detail the leader can act on (pick
        // another week); the generic text hid it. Same reader as the upload.
        const apiError = await readApiError(
          response,
          "보관함 악보를 주차에 반영하지 못했습니다.",
          []
        );
        throw new Error(alertMessageOf(apiError));
      }
      await Promise.all([fetchScores(), fetchLibrary()]);
      return { ok: true };
    } catch (err) {
      setError(err.message);
      return { ok: false, message: err.message };
    } finally {
      setIsPlacingSong(false);
    }
  };

  return {
    scores,
    totalSongs,
    librarySongs,
    error,
    isUploading,
    isUpdating,
    isPlacingSong,
    createScoreWithUpload,
    updateScore,
    deleteScore,
    placeSongOnWeek,
  };
}
