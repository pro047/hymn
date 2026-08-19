/**
 * @vitest-environment jsdom
 *
 * Page-level tests for the reset confirm form.
 *
 * Three things here are load-bearing and none of them is visible by reading the
 * JSX: the token travels in the body rather than the query, a 401 stays on this
 * page instead of bouncing to /login, and a success clears whatever session this
 * browser had. Each is pinned below.
 *
 * fireEvent rather than user-event, for the reason signup-page's tests give.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import ResetPasswordPage from "./reset-password-page";
import { INVALID_LINK_MESSAGE } from "../api/password-reset";
import { getAccessToken, getRefreshToken, setTokens } from "../lib/auth-storage";
import { PASSWORD_RESET_NOTICE } from "../lib/auth-notice";
import LoginPage from "./login-page";

type Reply = { status?: number; body?: unknown };

/** Full URLs the page requested, in call order. Kept as URLs rather than paths
 *  so the "token is not in the query string" assertion has something to read. */
let requestedUrls: string[] = [];
/** Bodies POSTed, in call order. */
let posted: unknown[] = [];

const VALID_TOKEN = "Zm9vYmFyYmF6cXV4MTIzNDU2Nzg5MA";
const NEW_PASSWORD = "NewPassw0rd";

function mockApi(reply: Reply = {}) {
  requestedUrls = [];
  posted = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const raw = String(input);
      const url = new URL(raw, "http://test.local");
      if (!url.pathname.endsWith("/auth/password-reset/confirm")) {
        throw new Error(`unexpected request to ${url.pathname}`);
      }
      requestedUrls.push(raw);
      posted.push(JSON.parse(String(init?.body ?? "null")));

      const status = reply.status ?? 204;
      return Promise.resolve({
        ok: status >= 200 && status < 300,
        status,
        json: () => Promise.resolve(reply.body ?? null),
      } as Response);
    })
  );
}

/** Renders the page at a tokened URL alongside a real /login, so a navigation
 *  away can be observed by what ends up on screen. */
function renderPage(token: string | null = VALID_TOKEN) {
  const path = token === null ? "/reset-password" : `/reset-password?token=${token}`;
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/reset-password" element={<ResetPasswordPage />} />
        <Route path="/login" element={<LoginPage />} />
      </Routes>
    </MemoryRouter>
  );
}

function fillPasswords(password = NEW_PASSWORD, confirm = password) {
  fireEvent.change(screen.getByLabelText("새 비밀번호"), { target: { value: password } });
  fireEvent.change(screen.getByLabelText("새 비밀번호 확인"), { target: { value: confirm } });
}

async function submit() {
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "비밀번호 재설정" }));
    await vi.advanceTimersByTimeAsync(0);
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  localStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  localStorage.clear();
});

describe("ResetPasswordPage", () => {
  it("sends the token from the link in the body, never in the URL", async () => {
    mockApi();
    renderPage();

    fillPasswords();
    await submit();

    expect(posted).toEqual([{ token: VALID_TOKEN, new_password: NEW_PASSWORD }]);
    // A token in a query string lands in access logs, Referer headers and
    // history — and possessing it is the whole credential.
    expect(requestedUrls[0]).not.toContain(VALID_TOKEN);
    expect(requestedUrls[0]).not.toContain("token=");
  });

  it("clears any session in this browser on success", async () => {
    mockApi();
    setTokens({ accessToken: "stale-access", refreshToken: "stale-refresh" });
    renderPage();

    fillPasswords();
    await submit();

    // The server revoked every session as part of the confirm, so these were
    // dead the moment it answered. Leaving them means the next request finds out.
    expect(getAccessToken()).toBeNull();
    expect(getRefreshToken()).toBeNull();
  });

  it("lands on the login screen with the reset notice", async () => {
    mockApi();
    renderPage();

    fillPasswords();
    await submit();

    expect(screen.getByText(PASSWORD_RESET_NOTICE)).toBeTruthy();
    expect(screen.getByRole("button", { name: "로그인" })).toBeTruthy();
  });

  it("shows the server's sentence for a spent link and stays on the page", async () => {
    const detail = "재설정 링크가 만료되었거나 이미 사용되었습니다. 다시 요청해 주세요.";
    mockApi({ status: 401, body: { detail } });
    renderPage();

    fillPasswords();
    await submit();

    // This is the apiFetch trap: routed through it, the 401 would be read as an
    // expired access token, fail to refresh, and replace this page with /login
    // via a promise that never settles — the user would never read the sentence.
    expect(screen.getByText(detail)).toBeTruthy();
    expect(screen.getByRole("button", { name: "비밀번호 재설정" })).toBeTruthy();
    expect(screen.queryByText(PASSWORD_RESET_NOTICE)).toBeNull();
  });

  it("renders no form when the link carried no token", () => {
    mockApi();
    renderPage(null);

    expect(screen.getByText(INVALID_LINK_MESSAGE)).toBeTruthy();
    expect(screen.queryByLabelText("새 비밀번호")).toBeNull();
    expect(screen.queryByRole("button", { name: "비밀번호 재설정" })).toBeNull();
  });

  it("treats a whitespace-only token as no token at all", () => {
    mockApi();
    // What a mail client that wrapped the URL can leave behind. Untrimmed it
    // passes an emptiness check and gets submitted as a space.
    renderPage("%20%20");

    expect(screen.getByText(INVALID_LINK_MESSAGE)).toBeTruthy();
    expect(screen.queryByLabelText("새 비밀번호")).toBeNull();
  });

  it("says the link is bad, not that a field is too short, for a truncated token", async () => {
    mockApi({
      status: 422,
      body: { detail: [{ type: "string_too_short", loc: ["body", "token"], msg: "…" }] },
    });
    renderPage("tooshort");

    fillPasswords();
    await submit();

    // There is no token input on this page, so a length rule about it would be
    // an instruction the user cannot follow. Without this the raw field name
    // leaks too: labelOf() falls back to "token" for anything unlabelled.
    expect(screen.getByText(INVALID_LINK_MESSAGE)).toBeTruthy();
    expect(screen.queryByText(/token/)).toBeNull();
  });

  it("does not show the English 'Not Found' when the feature is switched off", async () => {
    mockApi({ status: 404, body: { detail: "Not Found" } });
    renderPage();

    fillPasswords();
    await submit();

    // An unmounted FastAPI route answers with a string `detail`, which
    // normalizeApiError passes through in place of any fallback.
    expect(screen.queryByText("Not Found")).toBeNull();
    expect(screen.getByText(/사용할 수 없습니다/)).toBeTruthy();
  });

  it("does not reach the server when the two passwords differ", async () => {
    mockApi();
    renderPage();

    fillPasswords(NEW_PASSWORD, "NewPassw0rdX");
    await submit();

    expect(posted).toHaveLength(0);
    expect(screen.getByText("비밀번호가 일치하지 않습니다.")).toBeTruthy();
  });

  it("does not reach the server when the password breaks the signup rules", async () => {
    mockApi();
    renderPage();

    // Same newPasswordField signup uses: a reset must not be able to set a
    // password the signup form would have refused.
    fillPasswords("alllowercase1");
    await submit();

    expect(posted).toHaveLength(0);
  });
});
