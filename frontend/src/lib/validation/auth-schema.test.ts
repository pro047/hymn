import { describe, expect, it } from "vitest";
import { z } from "zod";

import {
  FIELDS_SETTLED_TOGETHER,
  JOIN_CODE_REQUIRED_MESSAGE,
  PASSWORD_RULE_HINT,
  loginSchema,
  signupFormSchema,
  signupSchema,
  toValidationError,
} from "./auth-schema";

const VALID_SIGNUP = {
  name: "tester",
  email: "tester@example.com",
  password: "Password1",
  church: "Test Church",
  church_address: "Seoul",
  phone: "01012345678",
  agreed_terms: true as const,
};

const signupWith = (overrides: Record<string, unknown>) => ({ ...VALID_SIGNUP, ...overrides });

/**
 * Same cases as backend/tests/test_auth_signup.py, which asserts a 422 for each.
 * If the two files disagree, one of the two rule sets has drifted.
 */
const REJECTED_BY_BACKEND: ReadonlyArray<[string, Record<string, unknown>, string]> = [
  ["약관에 동의하지 않으면", { agreed_terms: false }, "agreed_terms"],
  ["비밀번호에 대문자가 없으면", { password: "password1" }, "password"],
  ["비밀번호에 소문자가 없으면", { password: "PASSWORD1" }, "password"],
  ["비밀번호가 8자보다 짧으면", { password: "Pass1" }, "password"],
  ["비밀번호가 16자를 넘으면", { password: "PasswordPassword1" }, "password"],
  ["휴대폰 번호가 8자보다 짧으면", { phone: "010" }, "phone"],
];

describe("signupSchema", () => {
  it("백엔드가 받아주는 입력이면 통과해야 한다", () => {
    const result = signupSchema.safeParse(VALID_SIGNUP);

    expect(result.success).toBe(true);
  });

  it.each(REJECTED_BY_BACKEND)("%s 해당 필드에 오류를 내야 한다", (_label, overrides, field) => {
    const result = signupSchema.safeParse(signupWith(overrides));

    expect(result.success).toBe(false);
    expect(result.error?.issues.map((issue) => issue.path[0])).toContain(field);
  });

  it("공백만 입력된 필드는 서버에 빈 문자열로 보내기 전에 거부해야 한다", () => {
    // The page sends the trimmed value, so validating the untrimmed one would
    // let "   " through here and still get a 422 from min_length=1.
    const result = signupSchema.safeParse(signupWith({ name: "   " }));

    expect(result.success).toBe(false);
    expect(result.error?.issues[0]?.path[0]).toBe("name");
  });

  it("통과한 값은 다듬어진 전송 본문으로 나와야 한다", () => {
    const result = signupSchema.safeParse(
      signupWith({ name: "  홍길동  ", email: " Tester@Example.COM ", church: " 한빛교회 " })
    );

    expect(result.success).toBe(true);
    expect(result.data).toMatchObject({
      name: "홍길동",
      email: "tester@example.com",
      church: "한빛교회",
    });
  });

  it("비밀번호는 앞뒤 공백까지 그대로 보내야 한다", () => {
    // Trimming a password would silently change the credential the user typed.
    const result = signupSchema.safeParse(signupWith({ password: " Passwor1 " }));

    expect(result.success).toBe(true);
    expect(result.data?.password).toBe(" Passwor1 ");
  });
});

/**
 * The signup gate holds no email format rule, on purpose: zod's pattern and
 * pydantic's email_validator disagree on real addresses, and every disagreement
 * in this direction is a registration the server would have taken. The rule
 * still exists as a lookup trigger — see lib/email-check.test.ts, which pins the
 * same inputs from the other side.
 */
describe("가입 이메일 게이트", () => {
  it.each(["a@b.c", "한글@example.com", "a@한글.com", "a@example.c", "a@example-.com"])(
    "서버가 받아주는 주소 %s 로는 가입을 막지 않아야 한다",
    (email) => {
      expect(signupSchema.safeParse(signupWith({ email })).success).toBe(true);
    }
  );

  it("서버가 거부하는 주소도 통과시켜 422 판정에 맡겨야 한다", () => {
    // backend/tests/test_auth_signup.py asserts the matching 422 for "a@b". The
    // user reads a Korean field message through api-error.ts, so the cost of
    // deferring is one round trip, not a worse error.
    expect(signupSchema.safeParse(signupWith({ email: "a@b" })).success).toBe(true);
  });

  it("이메일 칸이 비어 있으면 요청을 보내지 않아야 한다", () => {
    const result = signupSchema.safeParse(signupWith({ email: "   " }));

    expect(result.success).toBe(false);
    expect(result.error?.issues[0]?.path[0]).toBe("email");
  });
});

describe("signupFormSchema", () => {
  // The two form-only fields the page supplies: what was typed in the confirm
  // box, and what the church lookup answered.
  const formWith = (overrides: Record<string, unknown> = {}) => ({
    ...VALID_SIGNUP,
    password_confirm: VALID_SIGNUP.password,
    church_is_registered: false,
    ...overrides,
  });

  it("비밀번호 확인이 일치하면 통과해야 한다", () => {
    const result = signupFormSchema.safeParse(formWith());

    expect(result.success).toBe(true);
  });

  it("비밀번호 확인이 다르면 확인 필드에 오류를 달아야 한다", () => {
    const result = signupFormSchema.safeParse(formWith({ password_confirm: "Password2" }));

    expect(result.success).toBe(false);
    expect(result.error?.issues[0]?.path).toEqual(["password_confirm"]);
  });

  it("불일치 오류가 붙는 필드는 짝 선언에 들어 있어야 한다", () => {
    // The page clears errors through FIELDS_SETTLED_TOGETHER. If the refine's
    // path above moves and this map does not, the message survives a fix.
    const result = signupFormSchema.safeParse(formWith({ password_confirm: "Password2" }));
    const reportedOn = String(result.error?.issues[0]?.path[0]);

    expect(FIELDS_SETTLED_TOGETHER[reportedOn]).toContain("password");
    expect(FIELDS_SETTLED_TOGETHER.password).toContain(reportedOn);
  });

  it("등록된 교회인데 초대 코드가 없으면 코드 필드에 오류를 달아야 한다", () => {
    const result = signupFormSchema.safeParse(formWith({ church_is_registered: true }));

    expect(result.success).toBe(false);
    expect(result.error?.issues[0]?.path).toEqual(["join_code"]);
    expect(result.error?.issues[0]?.message).toBe(JOIN_CODE_REQUIRED_MESSAGE);
  });

  it("새 교회면 초대 코드가 없어도 통과해야 한다", () => {
    // Founding a church is issued a code rather than asked for one; requiring it
    // here would make the first signup of any church impossible.
    expect(
      signupFormSchema.safeParse(formWith({ church_is_registered: true, join_code: "abcd2345" }))
        .success
    ).toBe(true);
    expect(signupFormSchema.safeParse(formWith()).success).toBe(true);
  });

  it("코드 요구 오류가 붙는 필드도 짝 선언에 들어 있어야 한다", () => {
    const result = signupFormSchema.safeParse(formWith({ church_is_registered: true }));
    const reportedOn = String(result.error?.issues[0]?.path[0]);

    expect(FIELDS_SETTLED_TOGETHER[reportedOn]).toContain("church");
    expect(FIELDS_SETTLED_TOGETHER.church).toContain(reportedOn);
  });

  it("초대 코드는 대소문자와 공백을 정리해 보내야 한다", () => {
    // The generated alphabet is lowercase, so a phone keyboard's automatic
    // capital must not travel to the server as a different code.
    const result = signupFormSchema.safeParse(
      formWith({ church_is_registered: true, join_code: "  ABCD2345  " })
    );

    expect(result.success && result.data.join_code).toBe("abcd2345");
  });

  it("초대 코드가 16자를 넘으면 거부해야 한다", () => {
    const result = signupFormSchema.safeParse(
      formWith({ church_is_registered: true, join_code: "a".repeat(17) })
    );

    expect(result.success).toBe(false);
    expect(result.error?.issues[0]?.path).toEqual(["join_code"]);
  });
});

describe("PASSWORD_RULE_HINT", () => {
  it("안내가 말하는 길이 경계가 실제 규칙과 같아야 한다", () => {
    // The hint is built from the same constants, so this fails only if someone
    // hand-writes the numbers back in.
    const [min, max] = (PASSWORD_RULE_HINT.match(/\d+/g) ?? []).map(Number);
    const password = (length: number) => "Aa1" + "x".repeat(length - 3);

    expect(signupSchema.safeParse(signupWith({ password: password(min) })).success).toBe(true);
    expect(signupSchema.safeParse(signupWith({ password: password(min - 1) })).success).toBe(false);
    expect(signupSchema.safeParse(signupWith({ password: password(max) })).success).toBe(true);
    expect(signupSchema.safeParse(signupWith({ password: password(max + 1) })).success).toBe(false);
  });
});

describe("loginSchema", () => {
  // Confirmed against pydantic EmailStr on 2026-07-30: every one of these
  // constructs a LoginRequest fine, and accounts using them can exist because
  // the pre-M2 signup page checked no email format at all. Rejecting them here
  // would lock those users out — there is no password reset yet.
  it.each([
    "a@b.c",
    "a@example.c",
    "한글@example.com",
    "a@한글.com",
    "kim%name@daum.net",
    "user=name@example.com",
    "first!last@example.com",
    "a@example-.com",
  ])("서버가 받아주는 주소 %s 로는 로그인을 막지 않아야 한다", (email) => {
    expect(loginSchema.safeParse({ email, password: "Password1" }).success).toBe(true);
  });

  it("이메일 칸이 비어 있으면 요청을 보내지 않아야 한다", () => {
    expect(loginSchema.safeParse({ email: "   ", password: "Password1" }).success).toBe(false);
  });

  it("17자 비밀번호는 로그인에서 허용해야 한다", () => {
    // Pinned against backend LoginRequest.password max_length=128: accounts made
    // before the 16-char signup cap must still be able to sign in.
    const seventeen = "PasswordPassword1";
    expect(seventeen).toHaveLength(17);

    expect(loginSchema.safeParse({ email: "a@b.co", password: seventeen }).success).toBe(true);
    expect(signupSchema.safeParse(signupWith({ password: seventeen })).success).toBe(false);
  });

  it("이메일은 소문자로 다듬어 보내야 한다", () => {
    const result = loginSchema.safeParse({ email: " Tester@Example.COM ", password: "Password1" });

    expect(result.data?.email).toBe("tester@example.com");
  });
});

describe("toValidationError", () => {
  it("필드별 첫 오류만 남기고 나머지는 버려야 한다", () => {
    const error = new z.ZodError([
      { code: "custom", path: ["password"], message: "첫 번째" },
      { code: "custom", path: ["password"], message: "두 번째" },
    ]);

    expect(toValidationError(error).fieldErrors).toEqual({ password: "첫 번째" });
  });

  it("경로가 없는 오류는 폼 단위 메시지로 올려야 한다", () => {
    const error = new z.ZodError([{ code: "custom", path: [], message: "폼 전체 오류" }]);

    const result = toValidationError(error);

    expect(result.formError).toBe("폼 전체 오류");
    expect(result.fieldErrors).toEqual({});
  });

  it("서버에 닿지 않았음을 status 0으로 표시해야 한다", () => {
    const result = toValidationError(signupSchema.safeParse(signupWith({ phone: "010" })).error!);

    expect(result.status).toBe(0);
  });
});
