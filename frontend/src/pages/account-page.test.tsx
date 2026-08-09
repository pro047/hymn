/**
 * @vitest-environment jsdom
 *
 * Page-level tests for the password change form. The rules themselves are
 * pinned in lib/validation/auth-schema.test.ts and mirrored by
 * backend/tests/test_auth_password.py; what is checked here is the wiring —
 * that the gate runs before the request, that the server's wording reaches the
 * screen, and that a success ends the session and says so on the next screen.
 *
 * The real LoginPage is mounted at /login rather than a stub, because the
 * confirmation is handed between the two files through router state and a stub
 * would pin only the writing half.
 *
 * jsdom has no rendering engine: colour and layout stay on the manual list.
 * Input goes through fireEvent, not user-event, which deadlocks against fake
 * timers (see signup-page.test.tsx).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import AccountPage from "./account-page";
import LoginPage from "./login-page";
import { PASSWORD_CHANGED_NOTICE } from "../lib/auth-notice";
import { PASSWORD_RULE_HINT } from "../lib/validation/auth-schema";

const CURRENT = "Password1";
const NEXT = "Newpassword1";

type Reply = { status?: number; body?: unknown };

/** Bodies posted to /auth/password, in call order. Its length is the request count. */
let posted: Array<Record<string, unknown>> = [];

function mockChangePassword(reply: Reply = {}) {
  posted = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://test.local");
      if (!url.pathname.endsWith("/auth/password")) {
        throw new Error(`unexpected request to ${url.pathname}`);
      }
      posted.push(JSON.parse(String(init?.body ?? "{}")));
      const status = reply.status ?? 204;
      return Promise.resolve({
        ok: status < 400,
        status,
        json: async () => {
          // A real 204 has no body and this is what fetch does with it. The
          // success path must not read one; if it starts to, this throws rather
          // than quietly handing it undefined.
          if (status === 204) throw new SyntaxError("Unexpected end of JSON input");
          return reply.body;
        },
      } as Response);
    })
  );
}

const renderAccount = () =>
  render(
    <MemoryRouter initialEntries={["/account"]}>
      <Routes>
        <Route path="/account" element={<AccountPage />} />
        <Route path="/login" element={<LoginPage />} />
      </Routes>
    </MemoryRouter>
  );

const type = (label: string, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } });

const fill = ({ current = CURRENT, next = NEXT, confirm = NEXT } = {}) => {
  type("현재 비밀번호", current);
  type("새 비밀번호", next);
  type("새 비밀번호 확인", confirm);
};

/** Submits and flushes the promises the click sets off. */
const submit = async () => {
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "비밀번호 변경" }));
  });
};

const onAccountPage = () => screen.queryByLabelText("새 비밀번호 확인") !== null;

beforeEach(() => {
  localStorage.setItem("hymn_access_token", "old-access");
  localStorage.setItem("hymn_refresh_token", "old-refresh");
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("비밀번호 변경", () => {
  it("성공하면 토큰을 지우고 로그인 화면으로 보내야 한다", async () => {
    mockChangePassword();
    renderAccount();

    fill();
    await submit();

    // The server revoked every refresh token the account had, this tab's
    // included, so leaving them in storage would only mean the next request
    // discovers that. Clearing them is also what stops LoginRoute from
    // bouncing this navigation straight back home.
    expect(localStorage.getItem("hymn_access_token")).toBeNull();
    expect(localStorage.getItem("hymn_refresh_token")).toBeNull();
    expect(onAccountPage()).toBe(false);
    expect(screen.getByRole("button", { name: "로그인" })).toBeTruthy();
  });

  it("성공하면 로그인 화면에 변경 안내를 보여줘야 한다", async () => {
    mockChangePassword();
    renderAccount();

    fill();
    await submit();

    // Without it the login screen appearing is indistinguishable from a session
    // that simply expired, and the user has no confirmation the change landed.
    expect(screen.getByText(PASSWORD_CHANGED_NOTICE)).toBeTruthy();
  });

  it("변경 전에 로그아웃된다는 것을 미리 알려야 한다", () => {
    mockChangePassword();
    renderAccount();

    // The consequence is not recoverable by going back, so it belongs next to
    // the button rather than in the confirmation afterwards.
    expect(screen.getByText(/모든 기기에서 로그아웃/)).toBeTruthy();
  });

  it("규칙에 어긋나는 새 비밀번호면 요청을 보내지 않아야 한다", async () => {
    mockChangePassword();
    renderAccount();

    // No uppercase. The server would answer 422; catching it here spares the
    // round trip and, on this route, a slot in a 10/minute budget.
    fill({ next: "newpassword1", confirm: "newpassword1" });
    await submit();

    expect(posted).toHaveLength(0);
    expect(screen.getByText("영문 대문자와 소문자를 모두 포함해야 합니다.")).toBeTruthy();
  });

  it("새 비밀번호가 현재 비밀번호와 같으면 요청을 보내지 않아야 한다", async () => {
    mockChangePassword();
    renderAccount();

    fill({ next: CURRENT, confirm: CURRENT });
    await submit();

    expect(posted).toHaveLength(0);
    // Filed under new_password rather than shown as an alert: the server's own
    // copy of this rule is a model validator and arrives with no field, so this
    // placement exists only here.
    expect(screen.getByLabelText("새 비밀번호").getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByText("새 비밀번호가 현재 비밀번호와 같습니다.")).toBeTruthy();
  });

  it("확인란이 다르면 짝 오류를 표시하고, 한쪽을 고치면 사라져야 한다", async () => {
    mockChangePassword();
    renderAccount();

    fill({ confirm: "Different1" });
    await submit();
    expect(posted).toHaveLength(0);
    expect(screen.getByText("비밀번호가 일치하지 않습니다.")).toBeTruthy();

    // The message is filed under new_password_confirm alone, so editing the
    // *other* half is what FIELDS_SETTLED_TOGETHER has to cover. Fixing it from
    // this side must not leave the error on a field that now matches.
    type("새 비밀번호", "Different1");

    expect(screen.queryByText("비밀번호가 일치하지 않습니다.")).toBeNull();
    expect(screen.getByLabelText("새 비밀번호 확인").getAttribute("aria-invalid")).toBe("false");
  });

  it("현재 비밀번호가 틀리면 화면에 남아 서버 문구를 보여줘야 한다", async () => {
    mockChangePassword({ status: 403, body: { detail: "현재 비밀번호가 올바르지 않습니다." } });
    renderAccount();

    fill();
    await submit();

    expect(screen.getByText("현재 비밀번호가 올바르지 않습니다.")).toBeTruthy();
    // 403 and not 401 is what keeps this true: apiFetch answers a 401 by
    // refreshing, retrying and then clearing storage, so a typo would sign the
    // user out instead of telling them about the typo.
    expect(onAccountPage()).toBe(true);
    expect(localStorage.getItem("hymn_access_token")).toBe("old-access");
  });

  it("실패하면 입력값을 지우지 않아야 한다", async () => {
    mockChangePassword({ status: 403, body: { detail: "현재 비밀번호가 올바르지 않습니다." } });
    renderAccount();

    fill();
    await submit();

    // Only the wrong field needs retyping. Clearing all three on a rejection
    // would make one typo cost the whole form.
    expect((screen.getByLabelText("새 비밀번호") as HTMLInputElement).value).toBe(NEXT);
  });

  it("비밀번호 규칙을 입력 전부터 보여줘야 한다", () => {
    mockChangePassword();
    renderAccount();

    expect(screen.getByText(PASSWORD_RULE_HINT)).toBeTruthy();
  });
});

describe("로그인 화면의 변경 안내", () => {
  it("그냥 로그인 화면에 오면 안내가 없어야 한다", () => {
    render(
      <MemoryRouter initialEntries={["/login"]}>
        <LoginPage />
      </MemoryRouter>
    );

    // It describes how the user got here. Showing it to everyone would tell a
    // visitor their password changed when it did not.
    expect(screen.queryByText(PASSWORD_CHANGED_NOTICE)).toBeNull();
  });
});
