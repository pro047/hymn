import { useCallback, useEffect, useRef, useState } from "react";

import { apiFetch } from "../../../api/client";
import { API_PATHS } from "../../../api/paths";
import { alertMessageOf, readApiError, toFormError } from "../../../lib/api-error";

const NETWORK_ERROR_MESSAGE = "네트워크 오류로 요청에 실패했습니다.";

/** A data: URL's payload as bytes, for uploading a canvas without re-encoding it.
 *
 * fetch(dataUrl).then(r => r.blob()) would be shorter and does work in a
 * browser, but jsdom does not implement fetch for the data: scheme — a test
 * that saved would fail on the transport rather than on anything this app
 * decides. Decoding it here keeps the two the same.
 */
export function dataUrlToBlob(dataUrl) {
  const [header, payload] = dataUrl.split(",");
  const type = header.match(/data:([^;]+)/)?.[1] ?? "application/octet-stream";
  const binary = atob(payload);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return new Blob([bytes], { type });
}

/** Loads what the editor opens with, and writes back what it produced.
 *
 * The canvas itself is not in here. This hook only knows two values — a
 * background image URL and a document — so the editor can be tested against
 * plain data and this can be tested without a canvas.
 *
 * `scoreId` null means the editor is closed; nothing is fetched and the last
 * sheet's data is dropped rather than left to flash under the next one.
 */
export function useScoreEdit(scoreId) {
  const [sourceImageUrl, setSourceImageUrl] = useState(null);
  const [editDoc, setEditDoc] = useState(null);
  const [hasEdit, setHasEdit] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState("");

  // Which sheet the screen is on, readable from a response sent for an
  // earlier one. Same reason use-conti keeps currentWeekRef: the GET effect
  // has a cleanup to hang `active` on, the save does not.
  const currentScoreIdRef = useRef(scoreId);
  useEffect(() => {
    currentScoreIdRef.current = scoreId;
  }, [scoreId]);

  useEffect(() => {
    if (!scoreId) {
      setSourceImageUrl(null);
      setEditDoc(null);
      setHasEdit(false);
      setError("");
      return undefined;
    }
    let active = true;
    setIsLoading(true);
    // Cleared before the fetch, not after it lands: opening a second sheet
    // while the first is still on screen would otherwise draw the previous
    // song's markings over the new song's image until the response arrived.
    setSourceImageUrl(null);
    setEditDoc(null);
    setHasEdit(false);
    setError("");
    apiFetch(API_PATHS.scoreEdit(scoreId))
      .then(async (response) => {
        if (!active) return;
        if (!response.ok) {
          const apiError = await readApiError(response, "악보를 불러오지 못했습니다.", []);
          setError(alertMessageOf(apiError));
          return;
        }
        const data = await response.json();
        setSourceImageUrl(data.source_image_url);
        setEditDoc(data.edit_doc);
        setHasEdit(Boolean(data.edited_file_uri));
      })
      .catch(() => {
        if (active) setError(alertMessageOf(toFormError(NETWORK_ERROR_MESSAGE)));
      })
      .finally(() => {
        if (active) setIsLoading(false);
      });
    return () => {
      active = false;
    };
  }, [scoreId]);

  /** Sign, upload, then record — in that order, and only on success of each.
   *
   * Recording first would point the week at an object that was never written,
   * which draws as a broken image instead of the sheet it had. The same
   * ordering the file-replacement path uses (use-scores.uploadReplacementFile).
   */
  const save = useCallback(
    async ({ dataUrl, doc }) => {
      if (!scoreId) return { ok: false };
      setIsSaving(true);
      setError("");
      try {
        const issued = await apiFetch(API_PATHS.scoreEditedFile(scoreId), { method: "POST" });
        if (!issued.ok) {
          // Through readApiError like every other call here. This route
          // answers 403 to a member editing somebody else's upload
          // (_writable_score_or_error), and a fixed "주소를 받지 못했습니다"
          // would replace that reason with one that explains nothing.
          const apiError = await readApiError(issued, "업로드 주소를 받지 못했습니다.", []);
          throw new Error(alertMessageOf(apiError));
        }
        const { upload_url: uploadUrl, s3_key: s3Key } = await issued.json();

        // Plain fetch, not apiFetch: this goes to S3, and the Authorization
        // header apiFetch attaches is not part of what the presigned URL was
        // signed over — sending it makes S3 reject the PUT.
        const uploaded = await fetch(uploadUrl, {
          method: "PUT",
          headers: { "Content-Type": "image/png" },
          body: dataUrlToBlob(dataUrl),
        });
        if (!uploaded.ok) {
          throw new Error("S3 업로드에 실패했습니다.");
        }

        const saved = await apiFetch(API_PATHS.scoreEdit(scoreId), {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ edited_file_uri: s3Key, edit_doc: doc }),
        });
        // A response for a sheet the editor has already left is dropped
        // rather than painted, the same way use-conti drops a stale PATCH.
        if (currentScoreIdRef.current !== scoreId) return { ok: false };
        if (!saved.ok) {
          const apiError = await readApiError(saved, "편집 내용을 저장하지 못했습니다.", []);
          throw new Error(alertMessageOf(apiError));
        }
        return { ok: true };
      } catch (err) {
        if (currentScoreIdRef.current !== scoreId) return { ok: false };
        const message = err?.message || alertMessageOf(toFormError(NETWORK_ERROR_MESSAGE));
        setError(message);
        return { ok: false, message };
      } finally {
        setIsSaving(false);
      }
    },
    [scoreId]
  );

  /** Back to the song's own sheet.
   *
   * Not the same as saving an empty canvas: that still flattens to a picture,
   * and the week would go on showing that copy rather than the song's file as
   * it changes.
   */
  const clear = useCallback(async () => {
    if (!scoreId) return { ok: false };
    setIsSaving(true);
    setError("");
    try {
      const response = await apiFetch(API_PATHS.scoreEdit(scoreId), { method: "DELETE" });
      if (currentScoreIdRef.current !== scoreId) return { ok: false };
      if (!response.ok) {
        const apiError = await readApiError(response, "편집 내용을 지우지 못했습니다.", []);
        const message = alertMessageOf(apiError);
        setError(message);
        return { ok: false, message };
      }
      return { ok: true };
    } catch {
      if (currentScoreIdRef.current !== scoreId) return { ok: false };
      const message = alertMessageOf(toFormError(NETWORK_ERROR_MESSAGE));
      setError(message);
      return { ok: false, message };
    } finally {
      setIsSaving(false);
    }
  }, [scoreId]);

  return { sourceImageUrl, editDoc, hasEdit, isLoading, isSaving, error, save, clear };
}
