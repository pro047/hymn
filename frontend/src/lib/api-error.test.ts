import { describe, expect, it } from "vitest";

import {
  alertMessageOf,
  clearFieldError,
  normalizeApiError,
  readApiError,
  toFormError,
  type ApiError,
} from "./api-error";

const SIGNUP_FIELDS = [
  "name",
  "email",
  "password",
  "password_confirm",
  "church",
  "church_address",
  "phone",
  "agreed_terms",
] as const;

// Recorded verbatim from the running backend on 2026-07-29:
//   POST /auth/signup {"email":"a@b","phone":"010", …} -> 422
// Hand-written fixtures drift from what FastAPI actually emits; this one cannot.
const REAL_422 = {
  detail: [
    {
      type: "value_error",
      loc: ["body", "email"],
      msg: "value is not a valid email address: The part after the @-sign is not valid. It should have a period.",
      input: "a@b",
      ctx: { reason: "The part after the @-sign is not valid. It should have a period." },
    },
    {
      type: "string_too_short",
      loc: ["body", "phone"],
      msg: "String should have at least 8 characters",
      input: "010",
      ctx: { min_length: 8 },
    },
  ],
};

// Recorded verbatim from the running backend on 2026-07-29, after M2 moved the
// rules into SignupRequest. Both items are `value_error` but must render very
// differently: EmailStr's wording is replaced, a field_validator's is kept.
const REAL_422_AFTER_M2 = {
  detail: [
    {
      type: "value_error",
      loc: ["body", "password"],
      msg: "Value error, 영문 대문자와 소문자를 모두 포함해야 합니다.",
      input: "password1",
      ctx: { error: {} },
    },
    {
      type: "value_error",
      loc: ["body", "agreed_terms"],
      msg: "Value error, 약관 동의가 필요합니다.",
      input: false,
      ctx: { error: {} },
    },
  ],
};

function responseStub(status: number, json: () => Promise<unknown>): Response {
  return { status, json } as unknown as Response;
}

describe("normalizeApiError", () => {
  it("422 배열 detail을 받으면 원인 필드별로 한국어 메시지를 매핑해야 한다", () => {
    const error = normalizeApiError(REAL_422, 422, "회원가입에 실패했습니다.", SIGNUP_FIELDS);

    expect(error.fieldErrors).toEqual({
      email: "올바른 이메일 주소를 입력해 주세요.",
      phone: "최소 8자 이상 입력해 주세요.",
    });
    // formError holds only what the server said; the alert copy is derived.
    expect(error.formError).toBe("");
    expect(error.status).toBe(422);
  });

  it("M2 field_validator가 낸 한국어 사유는 접두사만 떼고 그대로 보여줘야 한다", () => {
    const error = normalizeApiError(
      REAL_422_AFTER_M2,
      422,
      "회원가입에 실패했습니다.",
      SIGNUP_FIELDS
    );

    expect(error.fieldErrors).toEqual({
      password: "영문 대문자와 소문자를 모두 포함해야 합니다.",
      agreed_terms: "약관 동의가 필요합니다.",
    });
  });

  it("HTTPException 문자열 detail을 받으면 그대로 formError에 담아야 한다", () => {
    const error = normalizeApiError({ detail: "이미 사용 중인 이메일입니다." }, 409, "fallback");

    expect(error.formError).toBe("이미 사용 중인 이메일입니다.");
    expect(error.fieldErrors).toEqual({});
  });

  it("본문이 JSON이 아니면 fallback 메시지를 써야 한다", () => {
    const error = normalizeApiError(null, 500, "회원가입에 실패했습니다.");

    expect(error.formError).toBe("회원가입에 실패했습니다.");
    expect(error.fieldErrors).toEqual({});
  });

  it("폼이 렌더하지 않는 필드의 오류면 라벨을 붙여 formError로 승격해야 한다", () => {
    const error = normalizeApiError(REAL_422, 422, "fallback", ["name"]);

    // Silently dropping these would show a failed submit with no reason.
    expect(error.fieldErrors).toEqual({});
    expect(error.formError).toBe(
      "이메일: 올바른 이메일 주소를 입력해 주세요. 휴대폰 번호: 최소 8자 이상 입력해 주세요."
    );
  });

  it("loc이 body뿐이면 필드가 아니라 formError로 보내야 한다", () => {
    const error = normalizeApiError(
      { detail: [{ type: "missing", loc: ["body"], msg: "Field required" }] },
      422,
      "fallback",
      SIGNUP_FIELDS
    );

    expect(error.fieldErrors).toEqual({});
    expect(error.formError).toBe("필수 입력 항목입니다.");
  });

  it("loc이 중첩되어 있으면 잎 필드명을 골라야 한다", () => {
    const error = normalizeApiError(
      { detail: [{ type: "missing", loc: ["body", "items", 0, "email"], msg: "Field required" }] },
      422,
      "fallback",
      ["email"]
    );

    expect(error.fieldErrors).toEqual({ email: "필수 입력 항목입니다." });
  });

  it("같은 필드에 오류가 여러 개면 첫 번째만 남겨야 한다", () => {
    const error = normalizeApiError(
      {
        detail: [
          { type: "string_too_short", loc: ["body", "phone"], ctx: { min_length: 8 } },
          { type: "string_too_long", loc: ["body", "phone"], ctx: { max_length: 32 } },
        ],
      },
      422,
      "fallback",
      SIGNUP_FIELDS
    );

    expect(error.fieldErrors.phone).toBe("최소 8자 이상 입력해 주세요.");
  });

  it("ctx가 없는 string_too_short면 undefined 대신 서버 msg로 폴백해야 한다", () => {
    const error = normalizeApiError(
      {
        detail: [
          {
            type: "string_too_short",
            loc: ["body", "phone"],
            msg: "String should have at least 8 characters",
          },
        ],
      },
      422,
      "fallback",
      SIGNUP_FIELDS
    );

    expect(error.fieldErrors.phone).toBe("String should have at least 8 characters");
  });

  it("이메일 형식 오류는 필드명이 아니라 메시지로 판별해야 한다", () => {
    // M2 adds field validators; an email validator that is not EmailStr must
    // keep its own reason instead of being rewritten to the generic sentence.
    const error = normalizeApiError(
      {
        detail: [
          {
            type: "value_error",
            loc: ["body", "email"],
            msg: "Value error, 일회용 이메일은 사용할 수 없습니다.",
          },
        ],
      },
      422,
      "fallback",
      SIGNUP_FIELDS
    );

    expect(error.fieldErrors.email).toBe("일회용 이메일은 사용할 수 없습니다.");
  });

  it("한국어 매핑이 없는 타입이면 서버 msg를 그대로 보여줘야 한다", () => {
    const error = normalizeApiError(
      { detail: [{ type: "some_future_type", loc: ["body", "password"], msg: "weak password" }] },
      422,
      "fallback",
      SIGNUP_FIELDS
    );

    expect(error.fieldErrors.password).toBe("weak password");
  });
});

describe("alertMessageOf", () => {
  it("서버가 보낸 formError가 있으면 그대로 보여줘야 한다", () => {
    const error = normalizeApiError({ detail: "이미 사용 중인 이메일입니다." }, 409, "fallback");

    expect(alertMessageOf(error)).toBe("이미 사용 중인 이메일입니다.");
  });

  it("필드 오류만 있으면 요약 문구를 보여줘야 한다", () => {
    // Without this the submit button would look like it did nothing.
    const error = normalizeApiError(REAL_422, 422, "fallback", SIGNUP_FIELDS);

    expect(alertMessageOf(error)).toBe("입력한 정보를 다시 확인해 주세요.");
  });

  it("오류가 없으면 빈 문자열이어야 한다", () => {
    expect(alertMessageOf(null)).toBe("");
  });
});

describe("clearFieldError", () => {
  it("편집한 필드의 오류만 지워야 한다", () => {
    const error = normalizeApiError(REAL_422, 422, "fallback", SIGNUP_FIELDS);

    const next = clearFieldError(error, "phone");

    expect(next?.fieldErrors).toEqual({ email: "올바른 이메일 주소를 입력해 주세요." });
  });

  it("필드 오류를 지워도 서버가 보낸 폼 단위 메시지는 남아 있어야 한다", () => {
    // Blanking formError on an edit would leave a failed form with nothing on
    // screen explaining why — a 409/401 carries no field errors to fall back on.
    // The fixture must have BOTH so the clear path is actually exercised: with
    // an empty fieldErrors the function returns early and proves nothing.
    const error = normalizeApiError(REAL_422, 422, "fallback", ["phone"]);
    expect(error.formError).toBe("이메일: 올바른 이메일 주소를 입력해 주세요.");

    const next = clearFieldError(error, "phone");

    expect(next?.fieldErrors).toEqual({});
    expect(next?.formError).toBe("이메일: 올바른 이메일 주소를 입력해 주세요.");
  });

  it("필드 오류가 없는 폼 단위 오류는 그대로 유지해야 한다", () => {
    const error = normalizeApiError({ detail: "이미 사용 중인 이메일입니다." }, 409, "fallback");

    const next = clearFieldError(error, "phone");

    expect(alertMessageOf(next)).toBe("이미 사용 중인 이메일입니다.");
  });

  it("마지막 필드 오류가 사라지면 요약 문구도 함께 사라져야 한다", () => {
    const error = normalizeApiError(
      { detail: [{ type: "string_too_short", loc: ["body", "phone"], ctx: { min_length: 8 } }] },
      422,
      "fallback",
      SIGNUP_FIELDS
    );

    const next = clearFieldError(error, "phone");

    expect(alertMessageOf(next)).toBe("");
  });

  it("바뀔 게 없으면 같은 객체를 반환해야 한다", () => {
    const error: ApiError = { status: 409, formError: "중복", fieldErrors: { email: "중복" } };

    expect(clearFieldError(error, "phone")).toBe(error);
  });

  it("오류가 없으면 null을 유지해야 한다", () => {
    expect(clearFieldError(null, "email")).toBeNull();
  });
});

describe("readApiError", () => {
  it("본문이 422 JSON이면 필드 오류로 정규화해야 한다", async () => {
    const response = responseStub(422, () => Promise.resolve(REAL_422));

    const error = await readApiError(response, "fallback", SIGNUP_FIELDS);

    expect(error.status).toBe(422);
    expect(error.fieldErrors.phone).toBe("최소 8자 이상 입력해 주세요.");
  });

  it("json 파싱이 실패해도 던지지 않고 fallback과 상태 코드를 담아야 한다", async () => {
    // A proxy returning an HTML error page for a 500.
    const response = responseStub(500, () => Promise.reject(new Error("Unexpected token <")));

    const error = await readApiError(response, "회원가입에 실패했습니다.");

    expect(error.status).toBe(500);
    expect(error.formError).toBe("회원가입에 실패했습니다.");
  });
});

describe("toFormError", () => {
  it("서버에 닿지 못한 실패는 status 0으로 감싸야 한다", () => {
    const error = toFormError("네트워크 연결을 확인한 뒤 다시 시도해 주세요.");

    expect(error).toEqual({
      status: 0,
      formError: "네트워크 연결을 확인한 뒤 다시 시도해 주세요.",
      fieldErrors: {},
    });
  });
});
