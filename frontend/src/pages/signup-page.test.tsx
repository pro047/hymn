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
  CHURCH_CHECK_DEBOUNCE_MS,
  CHURCH_EXISTING_MESSAGE,
  CHURCH_NEW_MESSAGE,
} from "../lib/church-check";
import {
  EMAIL_AVAILABLE_MESSAGE,
  EMAIL_CHECK_DEBOUNCE_MS,
  EMAIL_TAKEN_MESSAGE,
} from "../lib/email-check";
import { JOIN_CODE_REQUIRED_MESSAGE, PASSWORD_RULE_HINT } from "../lib/validation/auth-schema";

type Reply = {
  status?: number;
  body?: unknown;
  delay?: number;
  /** Answer even after the request was aborted — i.e. the reply had already
   *  settled and only its continuation was left to run. */
  ignoreAbort?: boolean;
};

type Replies = {
  email?: Record<string, Reply>;
  church?: Record<string, Reply>;
  signup?: Reply;
};

/** Addresses asked about, in call order. Its length is the request count. */
let asked: string[] = [];
/** The same, for the church lookup. Kept apart so one endpoint's traffic cannot
 *  be mistaken for the other's when a test counts requests. */
let askedChurches: string[] = [];

function mockApi({ email = {}, church = {}, signup }: Replies = {}) {
  asked = [];
  askedChurches = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      // VITE_API_BASE_URL is undefined under test, so the path is relative.
      const url = new URL(String(input), "http://test.local");

      let reply: Reply;
      if (url.pathname.endsWith("/auth/check-church")) {
        const name = url.searchParams.get("name") ?? "";
        askedChurches.push(name);
        // Unregistered by default, so a test that says nothing about churches
        // takes the "founding a new one" path and is never asked for a code.
        reply = church[name] ?? { body: { exists: false } };
      } else if (url.pathname.endsWith("/auth/signup")) {
        reply = signup ?? { status: 500, body: { detail: "signup reply not configured" } };
      } else {
        const address = url.searchParams.get("email") ?? "";
        asked.push(address);
        reply = email[address] ?? { body: { available: true } };
      }
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

const mockCheckEmail = (replies: Record<string, Reply>) => mockApi({ email: replies });

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
const fillForm = async (
  overrides: { password?: string; password_confirm?: string; replies?: Replies } = {}
) => {
  mockApi(overrides.replies ?? {});
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

const EXISTING_CHURCH = "한빛교회";
/** What the server answers a signup that offered no code, or the wrong one. */
const INVALID_JOIN_CODE = "초대 코드가 올바르지 않습니다. 교회 리더에게 확인해 주세요.";
const joinCodeField = () => screen.queryByLabelText("초대 코드");
const typeChurch = (value: string) =>
  fireEvent.change(screen.getByLabelText("교회"), { target: { value } });

/** A church lookup that answers "already registered". */
const registered = { church: { [EXISTING_CHURCH]: { body: { exists: true } } } };

describe("회원가입 교회 자동 확인", () => {
  it("이미 등록된 교회면 초대 코드 칸을 보여줘야 한다", async () => {
    mockApi(registered);
    renderSignup();

    typeChurch(EXISTING_CHURCH);
    await settle();

    expect(screen.getByText(CHURCH_EXISTING_MESSAGE)).toBeTruthy();
    expect(joinCodeField()).toBeTruthy();
  });

  it("새 교회면 리더가 된다고 안내하고 코드는 묻지 않아야 한다", async () => {
    mockApi({ church: { 새로운교회: { body: { exists: false } } } });
    renderSignup();

    typeChurch("새로운교회");
    await settle();

    expect(screen.getByText(CHURCH_NEW_MESSAGE)).toBeTruthy();
    // Asking a founder for a code they were never given would be a dead end.
    expect(joinCodeField()).toBeNull();
  });

  it("타이핑이 이어지는 동안에는 요청을 보내지 않아야 한다", async () => {
    mockApi({});
    renderSignup();

    for (const partial of ["한", "한빛", "한빛교", EXISTING_CHURCH]) {
      typeChurch(partial);
      await advance(CHURCH_CHECK_DEBOUNCE_MS - 100);
    }
    expect(askedChurches).toHaveLength(0);

    await settle();
    expect(askedChurches).toEqual([EXISTING_CHURCH]);
  });

  it("한 글자만 입력한 동안에는 조회하지 않아야 한다", async () => {
    mockApi({});
    renderSignup();

    typeChurch("한");
    await settle();

    expect(askedChurches).toHaveLength(0);
  });

  it("앞뒤 공백만 다른 이름은 다시 물어보지 않아야 한다", async () => {
    mockApi(registered);
    renderSignup();

    typeChurch(EXISTING_CHURCH);
    await settle();
    typeChurch(`  ${EXISTING_CHURCH}  `);
    await settle();

    expect(askedChurches).toEqual([EXISTING_CHURCH]);
    expect(screen.getByText(CHURCH_EXISTING_MESSAGE)).toBeTruthy();
  });

  it("늦게 도착한 옛 교회명의 응답이 새 판정을 덮지 않아야 한다", async () => {
    // Same timeline as the email race above: the stale answer has to arrive
    // last, or a wrong verdict would be overwritten by the right one and the
    // guard would never be exercised.
    mockApi({
      church: {
        [EXISTING_CHURCH]: { body: { exists: true }, delay: 900, ignoreAbort: true },
        새로운교회: { body: { exists: false }, delay: 10 },
      },
    });
    renderSignup();

    typeChurch(EXISTING_CHURCH);
    await advance(CHURCH_CHECK_DEBOUNCE_MS);
    typeChurch("새로운교회");
    await settle();

    expect(screen.getByText(CHURCH_NEW_MESSAGE)).toBeTruthy();
    expect(joinCodeField()).toBeNull();
  });

  it("답을 못 받은 교회명은 캐시하지 않아 다시 물어봐야 한다", async () => {
    // A 429 must not pin a church to "unchecked" for the rest of the session:
    // the next attempt decides whether the code field is even offered.
    mockApi({
      church: { [EXISTING_CHURCH]: { status: 429, body: { detail: "요청이 많습니다." } } },
    });
    renderSignup();

    typeChurch(EXISTING_CHURCH);
    await settle();
    typeChurch("다른교회");
    await settle();
    typeChurch(EXISTING_CHURCH);
    await settle();

    expect(askedChurches.filter((name) => name === EXISTING_CHURCH)).toHaveLength(2);
  });

  it("429로 답을 못 받으면 코드 칸은 남기되 리더 안내는 하지 않아야 한다", async () => {
    // Hiding the field here would leave no way to supply the code the server is
    // about to refuse the signup for missing.
    mockApi({
      church: { [EXISTING_CHURCH]: { status: 429, body: { detail: "요청이 많습니다." } } },
    });
    renderSignup();

    typeChurch(EXISTING_CHURCH);
    await settle();

    expect(screen.queryByText(CHURCH_NEW_MESSAGE)).toBeNull();
    expect(joinCodeField()).toBeTruthy();
  });
});

describe("초대 코드 입력", () => {
  const fillJoiningExistingChurch = async () => {
    await fillForm({ replies: registered });
    submit();
  };

  it("등록된 교회에 코드 없이 제출하면 코드 칸에 오류를 달아야 한다", async () => {
    await fillJoiningExistingChurch();

    expect(screen.getByText(JOIN_CODE_REQUIRED_MESSAGE)).toBeTruthy();
    expect(joinCodeField()?.getAttribute("aria-invalid")).toBe("true");
  });

  it("코드를 입력하면 오류가 사라져야 한다", async () => {
    await fillJoiningExistingChurch();

    setField("초대 코드", "abcd2345");

    expect(screen.queryByText(JOIN_CODE_REQUIRED_MESSAGE)).toBeNull();
  });

  it("다른 교회로 고치면 앞서 붙은 코드 오류가 사라져야 한다", async () => {
    // The requirement belongs to the church, but zod files the message under
    // join_code alone, so the pairing in FIELDS_SETTLED_TOGETHER is what clears
    // it. The replacement has to be *another registered church*: switching to an
    // unregistered one hides the whole field, and the message would then be
    // absent whether or not it had been cleared — a test that passes for a
    // reason that has nothing to do with what it claims.
    await fillForm({
      replies: {
        church: {
          [EXISTING_CHURCH]: { body: { exists: true } },
          다른교회: { body: { exists: true } },
        },
      },
    });
    submit();
    expect(screen.getByText(JOIN_CODE_REQUIRED_MESSAGE)).toBeTruthy();

    typeChurch("다른교회");
    await settle();

    expect(joinCodeField()).toBeTruthy();
    expect(screen.queryByText(JOIN_CODE_REQUIRED_MESSAGE)).toBeNull();
  });

  it("이름을 고치는 것으로는 코드 오류가 사라지지 않아야 한다", async () => {
    await fillJoiningExistingChurch();

    setField("이름", "김철수");

    expect(screen.getByText(JOIN_CODE_REQUIRED_MESSAGE)).toBeTruthy();
  });

  /**
   * The lookup can be right when it answers and wrong by the time the form is
   * submitted — someone else founds the church in between. The server says so
   * with a 403, and before this the page threw that away: the cached "new"
   * verdict kept the code box hidden, and because the cache answers from memory
   * no amount of retyping brought it back. The signup was refused forever.
   */
  const submitAgainstAChurchFoundedMeanwhile = async () => {
    await fillForm({
      // No church override: the lookup answers "not registered", which is what
      // makes this a stale verdict rather than a wrong one.
      replies: { signup: { status: 403, body: { detail: INVALID_JOIN_CODE } } },
    });
    expect(joinCodeField()).toBeNull();

    submit();
    await settle();
  };

  it("코드 없이 제출해 403을 받으면 코드 칸이 나타나야 한다", async () => {
    await submitAgainstAChurchFoundedMeanwhile();

    expect(screen.getByText(INVALID_JOIN_CODE)).toBeTruthy();
    expect(joinCodeField()).toBeTruthy();
    // The hint has to flip too. Left saying "you will be the leader" it would
    // contradict the alert directly above it.
    expect(screen.getByText(CHURCH_EXISTING_MESSAGE)).toBeTruthy();
  });

  it("403 뒤에는 교회명을 바꿨다 되돌려도 다시 묻지 않고 코드 칸을 남겨야 한다", async () => {
    // Flipping the status alone would not survive this: the effect re-runs on
    // every church edit and reads the cache, so a stale `false` still in there
    // hides the field again the moment the name is retyped.
    await submitAgainstAChurchFoundedMeanwhile();

    typeChurch("다른교회");
    await settle();
    expect(joinCodeField()).toBeNull();

    typeChurch(EXISTING_CHURCH);
    await settle();

    expect(joinCodeField()).toBeTruthy();
    // Answered from the 403, not from a second round trip.
    expect(askedChurches).toEqual([EXISTING_CHURCH, "다른교회"]);
  });

  it("403이 아닌 실패는 교회 판정을 바꾸지 않아야 한다", async () => {
    // Only 403 carries the "this church exists" claim. Treating a 409 or a 500
    // the same way would put a code box in front of a founder who has none.
    await fillForm({
      replies: { signup: { status: 409, body: { detail: "이미 사용 중인 이메일입니다." } } },
    });

    submit();
    await settle();

    expect(screen.getByText(CHURCH_NEW_MESSAGE)).toBeTruthy();
    expect(joinCodeField()).toBeNull();
  });
});

describe("새 교회 창설 안내", () => {
  it("가입 응답에 코드가 있으면 이동 전에 코드를 보여줘야 한다", async () => {
    // The founder's one unprompted sight of the code. Navigating straight to the
    // home screen would leave them with no way to let anybody else in until
    // they found the management page.
    await fillForm({
      replies: {
        signup: {
          status: 201,
          body: {
            tokens: { access_token: "access", refresh_token: "refresh" },
            church: { code: "abcd2345" },
          },
        },
      },
    });

    submit();
    await settle();

    expect(screen.getByText("abcd2345")).toBeTruthy();
    expect(screen.getByText("가입이 완료됐습니다")).toBeTruthy();
  });

  it("코드가 없는 응답이면 코드 안내 없이 넘어가야 한다", async () => {
    // A member's signup carries no code, and a panel with nothing in it would
    // be worse than none.
    await fillForm({
      replies: {
        signup: {
          status: 201,
          body: {
            tokens: { access_token: "access", refresh_token: "refresh" },
            church: { code: null },
          },
        },
      },
    });

    submit();
    await settle();

    expect(screen.queryByText("가입이 완료됐습니다")).toBeNull();
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
