import { useCallback, useEffect, useState } from "react";

import { apiFetch } from "../../../api/client";
import { API_PATHS } from "../../../api/paths";
import { alertMessageOf, readApiError, toFormError } from "../../../lib/api-error";
import { flattenPages, moveItem, toOrderPayload, togglePageBreak } from "../../../lib/conti-order";
import { saveBlobAsFile } from "../../../lib/download";

const NETWORK_ERROR_MESSAGE = "네트워크 오류로 요청에 실패했습니다.";

/** Content-Disposition 의 filename. 없거나 형식이 다르면 null. */
function filenameFromResponse(response) {
  const header = response.headers?.get?.("Content-Disposition") ?? "";
  const match = header.match(/filename="?([^";]+)"?/);
  return match ? match[1] : null;
}

export function useConti(weekOfParam) {
  const [weekOf, setWeekOf] = useState(weekOfParam);
  const [pages, setPages] = useState(null);
  const [slotRatio, setSlotRatio] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [isDownloading, setIsDownloading] = useState(false);
  const [error, setError] = useState("");

  const items = flattenPages(pages ?? []);

  useEffect(() => {
    let active = true;
    setIsLoading(true);
    // Cleared, not just flagged loading: without this, moving from /conti/A
    // to /conti/B keeps A's songs painted while B loads, and if B's GET fails
    // A's conti stays on screen under an error alert — the leader would be
    // reordering week A believing it is week B.
    setPages(null);
    setSlotRatio(null);
    setWeekOf(weekOfParam);
    setError("");
    apiFetch(API_PATHS.weekConti(weekOfParam))
      .then(async (response) => {
        if (!active) return;
        if (!response.ok) {
          const apiError = await readApiError(response, "콘티를 불러오지 못했습니다.", []);
          setError(alertMessageOf(apiError));
          return;
        }
        const data = await response.json();
        setWeekOf(data.week_of);
        setSlotRatio(data.slot_ratio);
        setPages(data.pages);
        setError("");
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
  }, [weekOfParam]);

  // No optimistic update: `next` only builds the PATCH body. The screen keeps
  // rendering the last `pages` the server sent, because reordering also moves
  // page breaks (chunk_pages) and a client-computed layout could show the
  // wrong split for a moment.
  //
  // Reordering and breaking a page share this one path: both are edits to the
  // same list, and the server answers both with the whole conti. Two copies of
  // the save would be two places for the no-op check and the error handling to
  // drift apart.
  const save = useCallback(
    async (next) => {
      // Same reference means nothing moved (moveItem/togglePageBreak return the
      // input unchanged for a no-op), so the network is never touched.
      if (next === items) return;

      setIsSaving(true);
      setError("");
      try {
        const response = await apiFetch(API_PATHS.weekContiOrder(weekOfParam), {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ items: toOrderPayload(next) }),
        });
        if (!response.ok) {
          const apiError = await readApiError(response, "순서를 저장하지 못했습니다.", []);
          setError(alertMessageOf(apiError));
          return;
        }
        const data = await response.json();
        setWeekOf(data.week_of);
        setSlotRatio(data.slot_ratio);
        setPages(data.pages);
      } catch {
        setError(alertMessageOf(toFormError(NETWORK_ERROR_MESSAGE)));
      } finally {
        setIsSaving(false);
      }
    },
    [items, weekOfParam]
  );

  const moveSong = useCallback(
    async (from, to) => {
      // Guarded as well as disabled in the UI: a second edit started before the
      // first response lands would be computed from the pre-edit list, and
      // whichever response arrived last would win.
      if (isSaving) return;
      await save(moveItem(items, from, to));
    },
    [items, isSaving, save]
  );

  const toggleBreak = useCallback(
    async (index) => {
      if (isSaving) return;
      await save(togglePageBreak(items, index));
    },
    [items, isSaving, save]
  );

  const downloadPdf = useCallback(async () => {
    setIsDownloading(true);
    setError("");
    try {
      const response = await apiFetch(API_PATHS.weekPdf(weekOfParam));
      if (!response.ok) {
        const apiError = await readApiError(response, "PDF를 만들지 못했습니다.", []);
        setError(alertMessageOf(apiError));
        return;
      }
      const blob = await response.blob();
      // The server's own name first: `weekOf` starts out as the URL param and
      // is only corrected once the conti GET succeeds, so a failed (or still
      // pending) GET beside a successful PDF would otherwise save a Wednesday
      // name for a Sunday file. Content-Disposition carries the normalized
      // week (routes/conti.py:60); the state value is the fallback.
      saveBlobAsFile(blob, filenameFromResponse(response) ?? `conti-${weekOf}.pdf`);
    } catch {
      setError(alertMessageOf(toFormError(NETWORK_ERROR_MESSAGE)));
    } finally {
      setIsDownloading(false);
    }
  }, [weekOfParam, weekOf]);

  return {
    weekOf,
    pages,
    items,
    slotRatio,
    isLoading,
    isSaving,
    isDownloading,
    error,
    moveSong,
    toggleBreak,
    downloadPdf,
  };
}
