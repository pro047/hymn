import { describe, expect, it } from "vitest";
import { z } from "zod";

import { loginSchema, signupFormSchema, signupSchema, toValidationError } from "./auth-schema";

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
  ["이메일 도메인에 점이 없으면", { email: "a@b" }, "email"],
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
 * zod's email pattern and pydantic's email_validator do not agree everywhere.
 * These are the divergences found by cross-running both over 62 inputs; they are
 * pinned rather than fixed, so a future zod upgrade that shifts them shows up here.
 */
describe("백엔드와 판정이 갈리는 입력", () => {
  it.each(["a@b.c", "한글@example.com", "a@한글.com", "a@example.c"])(
    "%s 는 서버보다 엄격하게 거부해도 된다",
    (email) => {
      // Stricter than the server only costs a rejected keystroke, never a 422.
      expect(signupSchema.safeParse(signupWith({ email })).success).toBe(false);
    }
  );

  it("도메인이 하이픈으로 끝나는 주소는 통과시켜 서버 422에 맡긴다", () => {
    // The one known looser-than-server case. Pinned in
    // backend/tests/test_auth_signup.py, which asserts the matching 422 — the
    // user still sees a Korean field message via api-error.ts, not a crash.
    expect(signupSchema.safeParse(signupWith({ email: "a@example-.com" })).success).toBe(true);
  });
});

describe("signupFormSchema", () => {
  it("비밀번호 확인이 일치하면 통과해야 한다", () => {
    const result = signupFormSchema.safeParse({
      ...VALID_SIGNUP,
      password_confirm: VALID_SIGNUP.password,
    });

    expect(result.success).toBe(true);
  });

  it("비밀번호 확인이 다르면 확인 필드에 오류를 달아야 한다", () => {
    const result = signupFormSchema.safeParse({ ...VALID_SIGNUP, password_confirm: "Password2" });

    expect(result.success).toBe(false);
    expect(result.error?.issues[0]?.path).toEqual(["password_confirm"]);
  });
});

describe("loginSchema", () => {
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
