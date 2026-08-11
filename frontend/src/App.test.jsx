/**
 * @vitest-environment jsdom
 *
 * Routing only. The pages have their own tests; what is pinned here is that
 * /account is reachable and gated, because both failures are silent: the
 * catch-all `path="*"` redirects a missing route to "/" with no error, and a
 * missing guard would render the form to a signed-out visitor whose every
 * request then 401s.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import App from "./App";

const renderAt = (path) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>
  );

beforeEach(() => {
  // The pages under / fetch on mount; nothing here asserts on their content.
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.resolve({ ok: false, status: 401, json: async () => ({}) }))
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("라우팅", () => {
  it("로그인 상태에서 /account는 비밀번호 변경 화면을 보여줘야 한다", () => {
    localStorage.setItem("hymn_access_token", "token");

    renderAt("/account");

    expect(screen.getByLabelText("현재 비밀번호")).toBeTruthy();
  });

  it("로그아웃 상태에서 /account는 로그인으로 보내야 한다", () => {
    renderAt("/account");

    expect(screen.queryByLabelText("현재 비밀번호")).toBeNull();
    // LoginPage is what /login renders; its submit button names the screen.
    expect(screen.getByRole("button", { name: "로그인" })).toBeTruthy();
  });
});
