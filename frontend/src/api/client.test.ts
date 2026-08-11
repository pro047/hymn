/**
 * @vitest-environment jsdom
 *
 * The teardown races around apiFetch's token refresh. Two are pinned here:
 *
 *  - A logout that lands while a refresh is in flight must not be undone by the
 *    refresh's response writing a fresh pair back into storage.
 *  - A 401 refresh whose storage is empty (a logout, here or in another tab)
 *    must be read as "session gone", not "another tab refreshed for us" — the
 *    latter made apiFetch retry the original request with no auth header.
 *
 * apiFetch's rejected path ends in a never-settling promise (it navigates away),
 * so these drive the refresh to completion and assert on storage and on the
 * navigation, never on the apiFetch promise itself.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiFetch, logout } from "./client";

const REFRESH_URL = "/auth/refresh";
const LOGOUT_URL = "/auth/logout";
const APP_URL = "https://example.test/scores";

type Deferred = { promise: Promise<Response>; resolve: (r: Response) => void };

function deferred(): Deferred {
  let resolve!: (r: Response) => void;
  const promise = new Promise<Response>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status < 400,
    status,
    json: () => Promise.resolve(body),
  } as unknown as Response;
}

/** Lets the microtask queue drain so awaited continuations run. */
const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

let replaceSpy: ReturnType<typeof vi.fn>;

beforeEach(() => {
  localStorage.setItem("hymn_access_token", "A0");
  localStorage.setItem("hymn_refresh_token", "R0");
  replaceSpy = vi.fn();
  // jsdom's location.replace is a no-op that logs "Not implemented"; replace it
  // so the navigation is observable and silent.
  Object.defineProperty(window, "location", {
    value: { replace: replaceSpy },
    writable: true,
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("apiFetch 세션 종료 경합", () => {
  it("리프레시가 떠 있는 동안 로그아웃하면 토큰이 되살아나지 않아야 한다", async () => {
    const refresh = deferred();
    let appCalls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes(REFRESH_URL)) return refresh.promise;
        if (url.includes(LOGOUT_URL)) return Promise.resolve(jsonResponse(204, {}));
        // The original request: 401 first, so the refresh fires. The retry
        // after a "refreshed" result succeeds — that 200 is load-bearing. If
        // the retry 401'd too, the subsequent redirectToLogin would clear the
        // revived tokens and hide the very bug this test is for.
        appCalls += 1;
        return Promise.resolve(jsonResponse(appCalls === 1 ? 401 : 200, {}));
      })
    );

    // Not awaited: on the rejected path apiFetch never settles (it navigates).
    void apiFetch(APP_URL);
    await flush(); // let the 401 land and the refresh start

    logout();

    // Only now does the refresh succeed, carrying a usable pair — exactly the
    // late response that used to overwrite the cleared storage. Without the
    // epoch guard this writes A1/R1 back, the retry 200s, and the tab is
    // silently logged in again.
    refresh.resolve(jsonResponse(200, { access_token: "A1", refresh_token: "R1" }));
    await flush();
    await flush();

    expect(localStorage.getItem("hymn_access_token")).toBeNull();
    expect(localStorage.getItem("hymn_refresh_token")).toBeNull();
    expect(replaceSpy).toHaveBeenCalledWith("/login");
  });

  it("리프레시 401 시 스토리지가 비어 있으면 재로그인으로 보내야 한다", async () => {
    vi.useFakeTimers();
    const retryable = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes(REFRESH_URL)) return Promise.resolve(jsonResponse(401, {}));
      return Promise.resolve(jsonResponse(401, {}));
    });
    vi.stubGlobal("fetch", retryable);

    const inFlight = apiFetch(APP_URL);
    await vi.advanceTimersByTimeAsync(0); // 401 on the app request, refresh fires

    // The session goes away mid-grace (a logout in this or another tab clears
    // storage). Empty storage must read as "gone", not as a peer rotation.
    localStorage.clear();
    await vi.advanceTimersByTimeAsync(750); // run out the grace window

    void inFlight; // ends in the never-settling navigation; do not await it
    expect(replaceSpy).toHaveBeenCalledWith("/login");
    // The original request must not have been retried once the refresh failed:
    // a retry here would carry no Authorization header.
    const retried = retryable.mock.calls.filter(([u]) => String(u) === APP_URL);
    expect(retried).toHaveLength(1);

    vi.useRealTimers();
  });

  it("다른 탭이 새 토큰을 넣어줬으면 그 토큰으로 재시도해야 한다", async () => {
    let appCalls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes(REFRESH_URL)) {
          // Our own refresh loses the race: another tab already rotated, so the
          // server rejects this spent token. But storage now holds that tab's
          // fresh pair, so this is a recovery, not a logout.
          localStorage.setItem("hymn_access_token", "A1");
          localStorage.setItem("hymn_refresh_token", "R1");
          return Promise.resolve(jsonResponse(401, {}));
        }
        appCalls += 1;
        return Promise.resolve(jsonResponse(appCalls === 1 ? 401 : 200, {}));
      })
    );

    const response = await apiFetch(APP_URL);

    expect(response.status).toBe(200);
    expect(replaceSpy).not.toHaveBeenCalled();
    expect(localStorage.getItem("hymn_access_token")).toBe("A1");
  });
});
