/**
 * @vitest-environment jsdom
 *
 * Page-level tests for the signup email lookup. The judgement itself is pinned
 * in lib/email-check.test.ts; what is checked here is the wiring around it —
 * that the timer, the abort, the cache and the "is this answer still current?"
 * guard are connected to the field the user types into.
 *
 * jsdom carries no rendering engine, so nothing below asserts on colour or
 * layout. That half stays on the manual checklist.
 *
 * Input goes through fireEvent rather than user-event: every test here drives a
 * fake clock, and user-event deadlocks against one unless the clock is allowed
 * to advance with real time — which would make the debounce assertions depend on
 * how fast the machine ran them. The logic under test keys off the field's
 * value, not off individual key events, so nothing is lost by firing `change`.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import SignupPage from "./signup-page";
import {
  EMAIL_AVAILABLE_MESSAGE,
  EMAIL_CHECK_DEBOUNCE_MS,
  EMAIL_TAKEN_MESSAGE,
} from "../lib/email-check";
import { PASSWORD_RULE_HINT } from "../lib/validation/auth-schema";

type Reply = {
  status?: number;
  body?: unknown;
  delay?: number;
  /** Answer even after the request was aborted — i.e. the reply had already
   *  settled and only its continuation was left to run. */
  ignoreAbort?: boolean;
};

/** Addresses asked about, in call order. Its length is the request count. */
let asked: string[] = [];

function mockCheckEmail(replies: Record<string, Reply>) {
  asked = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      // VITE_API_BASE_URL is undefined under test, so the path is relative.
      const url = new URL(String(input), "http://test.local");
      const email = url.searchParams.get("email") ?? "";
      asked.push(email);

      const reply = replies[email] ?? { body: { available: true } };
      const status = reply.status ?? 200;

      return new Promise((resolve, reject) => {
        setTimeout(() => {
          if (init?.signal?.aborted && !reply.ignoreAbort) {
            reject(new DOMException("Aborted", "AbortError"));
            return;
          }
          resolve({ ok: status < 400, status, json: async () => reply.body } as Response);
        }, reply.delay ?? 0);
      });
    })
  );
}

const renderSignup = () =>
  render(
    // SignupPage renders a <Link>, which needs a router above it.
    <MemoryRouter>
      <SignupPage />
    </MemoryRouter>
  );

const emailField = () => screen.getByLabelText("이메일");

const typeEmail = (value: string) => fireEvent.change(emailField(), { target: { value } });

/** Runs the fake clock forward, flushing the promises each timer wakes. */
const advance = async (ms: number) => {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
};

/** Past the debounce and any mocked reply delay. */
const settle = () => advance(EMAIL_CHECK_DEBOUNCE_MS + 500);

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("회원가입 이메일 자동 조회", () => {
  it("이미 쓰이는 주소면 제출 없이 중복 안내를 보여줘야 한다", async () => {
    mockCheckEmail({ "taken@example.com": { body: { available: false } } });
    renderSignup();

    typeEmail("taken@example.com");
    await settle();

    expect(screen.getByText(EMAIL_TAKEN_MESSAGE)).toBeTruthy();
    expect(emailField().getAttribute("aria-invalid")).toBe("true");
  });

  it("쓸 수 있는 주소면 사용 가능 안내를 보여줘야 한다", async () => {
    mockCheckEmail({ "free@example.com": { body: { available: true } } });
    renderSignup();

    typeEmail("free@example.com");
    await settle();

    expect(screen.getByText(EMAIL_AVAILABLE_MESSAGE)).toBeTruthy();
    expect(emailField().getAttribute("aria-invalid")).toBe("false");
  });

  it("타이핑이 이어지는 동안에는 요청을 보내지 않아야 한다", async () => {
    // The endpoint allows 10/minute per IP; one request per keystroke would 429
    // a user in the middle of a single address.
    mockCheckEmail({});
    renderSignup();

    for (const partial of ["f", "fr", "free@e", "free@example.co", "free@example.com"]) {
      typeEmail(partial);
      await advance(EMAIL_CHECK_DEBOUNCE_MS - 100);
    }
    expect(asked).toHaveLength(0);

    await settle();
    expect(asked).toEqual(["free@example.com"]);
  });

  it("형식이 덜 갖춰진 값으로는 조회하지 않아야 한다", async () => {
    mockCheckEmail({});
    renderSignup();

    typeEmail("free@");
    await settle();

    expect(asked).toHaveLength(0);
  });

  it("대소문자와 공백만 다른 값은 다시 물어보지 않아야 한다", async () => {
    mockCheckEmail({ "taken@example.com": { body: { available: false } } });
    renderSignup();

    typeEmail("taken@example.com");
    await settle();
    typeEmail(" TAKEN@Example.COM ");
    await settle();

    expect(asked).toEqual(["taken@example.com"]);
    expect(screen.getByText(EMAIL_TAKEN_MESSAGE)).toBeTruthy();
  });

  it("늦게 도착한 옛 주소의 응답이 새 주소의 판정을 덮지 않아야 한다", async () => {
    // `ignoreAbort` reproduces what the AbortController cannot cover: the reply
    // had already settled and only its continuation was still queued. Only the
    // "is this answer about what is on screen now?" check stops it.
    //
    // The old address must answer *after* the new one, or a wrongly applied
    // verdict is immediately overwritten by the correct one and the assertion
    // below cannot see it. Timeline: A is asked at 500 and answers at 1400,
    // B is asked at 1000 and answers at 1010.
    mockCheckEmail({
      "slow-taken@example.com": { body: { available: false }, delay: 900, ignoreAbort: true },
      "quick-free@example.com": { body: { available: true }, delay: 10 },
    });
    renderSignup();

    typeEmail("slow-taken@example.com");
    await advance(EMAIL_CHECK_DEBOUNCE_MS);
    typeEmail("quick-free@example.com");
    await settle();

    expect(asked).toEqual(["slow-taken@example.com", "quick-free@example.com"]);
    expect(screen.queryByText(EMAIL_TAKEN_MESSAGE)).toBeNull();
    expect(screen.getByText(EMAIL_AVAILABLE_MESSAGE)).toBeTruthy();
  });

  it("서버가 422로 거부하는 주소는 오류가 아니라 무표시여야 한다", async () => {
    // looksLikeEmail accepts a@example-.com and EmailStr does not. The lookup is
    // a convenience, so a value it cannot answer for gets no verdict at all.
    mockCheckEmail({ "a@example-.com": { status: 422, body: { detail: [] } } });
    renderSignup();

    typeEmail("a@example-.com");
    await settle();

    expect(asked).toEqual(["a@example-.com"]);
    expect(screen.queryByText(EMAIL_TAKEN_MESSAGE)).toBeNull();
    expect(screen.queryByText(EMAIL_AVAILABLE_MESSAGE)).toBeNull();
  });

  it("429를 받으면 중복으로도 사용가능으로도 단정하지 않아야 한다", async () => {
    mockCheckEmail({ "free@example.com": { status: 429, body: { detail: "요청이 많습니다." } } });
    renderSignup();

    typeEmail("free@example.com");
    await settle();

    expect(screen.queryByText(EMAIL_TAKEN_MESSAGE)).toBeNull();
    expect(screen.queryByText(EMAIL_AVAILABLE_MESSAGE)).toBeNull();
  });

  it("답을 못 받은 주소는 캐시하지 않아 다시 물어봐야 한다", async () => {
    mockCheckEmail({ "free@example.com": { status: 429, body: { detail: "요청이 많습니다." } } });
    renderSignup();

    typeEmail("free@example.com");
    await settle();
    typeEmail("other@example.com");
    await settle();
    typeEmail("free@example.com");
    await settle();

    // A 429 must not pin an address to "unchecked" for the rest of the session.
    expect(asked.filter((email) => email === "free@example.com")).toHaveLength(2);
  });
});

const MISMATCH = "비밀번호가 일치하지 않습니다.";

const setField = (label: string, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } });

const submit = () => fireEvent.click(screen.getByRole("button", { name: "회원가입" }));

/** Every field valid except what the caller overrides. */
const fillForm = async (overrides: { password?: string; password_confirm?: string } = {}) => {
  mockCheckEmail({});
  renderSignup();

  setField("이름", "홍길동");
  setField("이메일", "tester@example.com");
  setField("비밀번호", overrides.password ?? "Password1");
  setField("비밀번호 확인", overrides.password_confirm ?? "Password1");
  setField("교회", "한빛교회");
  setField("교회주소", "서울");
  setField("휴대폰 번호", "01012345678");
  fireEvent.click(screen.getByRole("checkbox"));

  // The lookup has to finish first: submitting mid-check is blocked on purpose,
  // which would mask whatever the test is actually about.
  await settle();
};

const fillWithMismatch = async () => {
  await fillForm({ password: "Password1", password_confirm: "Password2" });
  submit();
};

describe("비밀번호 확인 오류", () => {
  it("불일치로 제출하면 확인 칸에 오류를 달아야 한다", async () => {
    await fillWithMismatch();

    expect(screen.getByText(MISMATCH)).toBeTruthy();
    expect(screen.getByLabelText("비밀번호 확인").getAttribute("aria-invalid")).toBe("true");
  });

  it("비밀번호 칸을 고쳐 일치시키면 오류가 사라져야 한다", async () => {
    // The rule spans two fields but zod files it under one, so editing the side
    // that carries no message used to leave it on screen.
    await fillWithMismatch();

    setField("비밀번호", "Password2");

    expect(screen.queryByText(MISMATCH)).toBeNull();
    expect(screen.getByLabelText("비밀번호 확인").getAttribute("aria-invalid")).toBe("false");
  });

  it("확인 칸을 고쳐도 오류가 사라져야 한다", async () => {
    await fillWithMismatch();

    setField("비밀번호 확인", "Password1");

    expect(screen.queryByText(MISMATCH)).toBeNull();
  });

  it("이름을 고치는 것으로는 비밀번호 오류가 사라지지 않아야 한다", async () => {
    // The pairing must stay narrow: an unrelated keystroke clearing a real error
    // would hide a mistake the user has not fixed.
    await fillWithMismatch();

    setField("이름", "김철수");

    expect(screen.getByText(MISMATCH)).toBeTruthy();
  });

  it("불일치를 해소하고 다시 제출하면 막히지 않아야 한다", async () => {
    await fillWithMismatch();

    setField("비밀번호", "Password2");
    submit();

    expect(screen.queryByText(MISMATCH)).toBeNull();
    await settle();
  });
});

describe("비밀번호 규칙 안내", () => {
  it("오류가 없어도 규칙을 항상 보여줘야 한다", () => {
    // Before this, the rules could only be discovered one rejected submit at a time.
    mockCheckEmail({});
    renderSignup();

    expect(screen.getByText(PASSWORD_RULE_HINT)).toBeTruthy();
  });

  it("오류가 떠도 규칙 안내는 남아 있어야 한다", async () => {
    await fillForm({ password: "short", password_confirm: "short" });

    submit();

    // Asserting through aria-describedby rather than the message text: the
    // "최소 8자" wording is shared with the phone field, and this also pins that
    // both descriptions stay attached to the input.
    expect(screen.getByLabelText("비밀번호").getAttribute("aria-describedby")).toBe(
      "password-error password-hint"
    );
    expect(screen.getByText(PASSWORD_RULE_HINT)).toBeTruthy();
  });

  it("규칙 안내를 오류와 함께 읽도록 연결해야 한다", () => {
    mockCheckEmail({});
    renderSignup();

    expect(screen.getByLabelText("비밀번호").getAttribute("aria-describedby")).toBe(
      "password-hint"
    );
  });
});
