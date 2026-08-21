/**
 * @vitest-environment jsdom
 *
 * Routing, plus the one seam the pages cannot test alone. What is pinned here
 * is that /account is reachable and gated, because both failures are silent:
 * the catch-all `path="*"` redirects a missing route to "/" with no error, and
 * a missing guard would render the form to a signed-out visitor whose every
 * request then 401s.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
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

describe("헤더", () => {
  // Neither side can pin this alone: App builds the group, HomePage owns the
  // header. Queried through the landmark rather than by name, so going back to
  // a floating layer fails here even though the buttons would still render.
  it("로그인 상태에서 계정과 로그아웃은 헤더 안에 있어야 한다", () => {
    localStorage.setItem("hymn_access_token", "token");
    // Answers 200, unlike the 401 stub the routing tests share. A 401 here
    // takes the refresh path, finds no refresh token, and endSession() tears
    // down the very session this test is named for — synchronous assertions
    // would still pass, so the arrangement has to be right on its own.
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve({ ok: true, status: 200, json: async () => [] }))
    );

    renderAt("/");

    const header = within(screen.getByRole("banner"));
    expect(header.getByRole("link", { name: "계정" })).toBeTruthy();
    expect(header.getByRole("button", { name: "로그아웃" })).toBeTruthy();
  });
});
