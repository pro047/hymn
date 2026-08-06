import { useEffect, useRef, useState, type ChangeEvent, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import { requestAuth } from "../api/auth";
import { fetchEmailAvailability } from "../api/check-email";
import { API_PATHS } from "../api/paths";
import {
  alertMessageOf,
  clearFieldError,
  clearFieldErrors,
  toFormError,
  type ApiError,
} from "../lib/api-error";
import { setTokens } from "../lib/auth-storage";
import {
  EMAIL_AVAILABLE_MESSAGE,
  EMAIL_CHECK_DEBOUNCE_MS,
  EMAIL_TAKEN_MESSAGE,
  planEmailCheck,
  resolveEmailCheck,
  type EmailCheckStatus,
} from "../lib/email-check";
import {
  FIELDS_SETTLED_TOGETHER,
  PASSWORD_RULE_HINT,
  signupFormSchema,
  toValidationError,
} from "../lib/validation/auth-schema";
import { Alert, AlertDescription, AlertTitle } from "../components/ui/alert";
import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";

// Backend field names this form renders inline; anything else lands in the alert.
const RENDERED_FIELDS = [
  "name",
  "email",
  "password",
  "password_confirm",
  "church",
  "church_address",
  "phone",
  "agreed_terms",
] as const;

// What the lookup shows under the email field. `unknown` is absent on purpose:
// "we did not check" is not worth a line of its own, and the address may simply
// be half-typed.
const EMAIL_STATUS_HINT: Partial<Record<EmailCheckStatus, { text: string; className: string }>> = {
  checking: { text: "이메일 중복 확인 중...", className: "text-stone-500" },
  available: { text: EMAIL_AVAILABLE_MESSAGE, className: "text-emerald-600" },
  taken: { text: EMAIL_TAKEN_MESSAGE, className: "text-red-500" },
};

export default function SignupPage() {
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [church, setChurch] = useState("");
  const [churchAddress, setChurchAddress] = useState("");
  const [phone, setPhone] = useState("");
  const [agreed, setAgreed] = useState(false);
  const [apiError, setApiError] = useState<ApiError | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [emailStatus, setEmailStatus] = useState<EmailCheckStatus>("unknown");

  // Read when an answer comes back, so a reply can be compared against what is
  // in the field *now* rather than against the value that requested it.
  const emailRef = useRef("");
  // Answers already received, keyed by normalized address. A ref, not state:
  // writing to it must never re-render, and the effect below reads it fresh.
  const cacheRef = useRef(new Map<string, boolean>());

  const fieldErrors = apiError?.fieldErrors ?? {};
  const alertMessage = alertMessageOf(apiError);
  // A real validation error outranks the lookup: it is the thing to fix first.
  const emailHint = fieldErrors.email ? undefined : EMAIL_STATUS_HINT[emailStatus];

  useEffect(() => {
    emailRef.current = email;

    const plan = planEmailCheck(email, cacheRef.current);
    setEmailStatus(plan.status);
    if (plan.action !== "query") return;

    const controller = new AbortController();
    const timer = setTimeout(async () => {
      const available = await fetchEmailAvailability(plan.key, controller.signal);
      // Only verdicts are worth remembering; a 429 would otherwise pin an
      // address to "unchecked" for the rest of the session.
      if (available !== null) cacheRef.current.set(plan.key, available);

      // The cleanup below already cancels this effect's work, but an in-flight
      // promise can still run its continuation after an abort. This asks the
      // narrower question — is this answer about the address on screen? — and is
      // what keeps a slow reply from stamping its verdict on a newer value.
      const resolution = resolveEmailCheck(plan.key, emailRef.current, available);
      if (resolution.apply) setEmailStatus(resolution.status);
    }, EMAIL_CHECK_DEBOUNCE_MS);

    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [email]);

  const handleFieldChange =
    (field: string, setValue: (value: string) => void) =>
    (event: ChangeEvent<HTMLInputElement>) => {
      setValue(event.target.value);
      // Also drops errors belonging to fields this one is judged against, so a
      // mismatch fixed from either side stops being reported.
      setApiError((previous) =>
        clearFieldErrors(previous, [field, ...(FIELDS_SETTLED_TOGETHER[field] ?? [])])
      );
    };

  const handleAgreedChange = (event: ChangeEvent<HTMLInputElement>) => {
    setAgreed(event.target.checked);
    setApiError((previous) => clearFieldError(previous, "agreed_terms"));
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (isSubmitting) return;

    // Same rules as the server, checked first so a fixable mistake costs no round
    // trip. `password_confirm` is form-only and is dropped from the request body.
    const parsed = signupFormSchema.safeParse({
      name,
      email,
      password,
      password_confirm: passwordConfirm,
      church,
      church_address: churchAddress,
      phone,
      agreed_terms: agreed,
    });
    if (!parsed.success) {
      setApiError(toValidationError(parsed.error));
      return;
    }

    // An answer is seconds away, and sending now would race it into a 409 that
    // reads worse than waiting. Reported rather than enforced by disabling the
    // button: a submit that silently does nothing has no way to explain itself.
    if (emailStatus === "checking") {
      setApiError(toFormError("이메일 중복 확인 중입니다. 잠시 후 다시 시도해 주세요."));
      return;
    }

    const { password_confirm: _passwordConfirm, ...body } = parsed.data;

    setApiError(null);
    setIsSubmitting(true);

    try {
      const outcome = await requestAuth({
        url: API_PATHS.authSignup,
        body,
        failureMessage: "회원가입에 실패했습니다.",
        // The account exists at this point, so retrying signup would only 409.
        unreadableMessage:
          "회원가입은 완료됐지만 자동 로그인에 실패했습니다. 로그인 화면에서 로그인해 주세요.",
        renderedFields: RENDERED_FIELDS,
      });

      if (!outcome.ok) {
        setApiError(outcome.error);
        return;
      }

      setTokens(outcome.tokens);
      navigate("/", { replace: true });
    } catch {
      // requestAuth already classified every request failure; anything left is
      // local (a blocked localStorage write), so it must not blame the network.
      setApiError(toFormError("요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요."));
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-white px-4 text-stone-900 sm:px-6 lg:px-8">
      <div className="mx-auto w-full max-w-md">
        <Card className="border-stone-200">
          <CardContent className="pt-6">
            <p className="mb-4 text-center text-lg font-normal text-stone-300">H Y M N</p>
            <form className="space-y-4" onSubmit={handleSubmit}>
              <div className="space-y-2">
                <Label htmlFor="name" className="text-[14px] text-stone-600">
                  이름
                </Label>
                <Input
                  id="name"
                  type="text"
                  placeholder="홍길동"
                  autoComplete="name"
                  value={name}
                  onChange={handleFieldChange("name", setName)}
                  aria-invalid={Boolean(fieldErrors.name)}
                  aria-describedby={fieldErrors.name ? "name-error" : undefined}
                />
                {fieldErrors.name ? (
                  <p id="name-error" className="text-[12px] text-red-500">
                    {fieldErrors.name}
                  </p>
                ) : null}
              </div>

              <div className="space-y-2">
                <Label htmlFor="email" className="text-[14px] text-stone-600">
                  이메일
                </Label>
                <Input
                  id="email"
                  type="email"
                  placeholder="you@church.org"
                  autoComplete="email"
                  value={email}
                  onChange={handleFieldChange("email", setEmail)}
                  aria-invalid={Boolean(fieldErrors.email) || emailStatus === "taken"}
                  aria-describedby={
                    fieldErrors.email ? "email-error" : emailHint ? "email-status" : undefined
                  }
                />
                {fieldErrors.email ? (
                  <p id="email-error" className="text-[12px] text-red-500">
                    {fieldErrors.email}
                  </p>
                ) : null}
                {emailHint ? (
                  // The result arrives without the user acting, so it has to be
                  // announced rather than merely rendered.
                  <p
                    id="email-status"
                    aria-live="polite"
                    className={`text-[12px] ${emailHint.className}`}
                  >
                    {emailHint.text}
                  </p>
                ) : null}
              </div>

              <div className="space-y-2">
                <Label htmlFor="password" className="text-[14px] text-stone-600">
                  비밀번호
                </Label>
                <Input
                  id="password"
                  type="password"
                  placeholder="비밀번호"
                  autoComplete="new-password"
                  value={password}
                  onChange={handleFieldChange("password", setPassword)}
                  aria-invalid={Boolean(fieldErrors.password)}
                  // Both ids: the hint stays true whether or not there is an
                  // error, so a screen reader should hear it either way.
                  aria-describedby={
                    fieldErrors.password ? "password-error password-hint" : "password-hint"
                  }
                />
                {fieldErrors.password ? (
                  <p id="password-error" className="text-[12px] text-red-500">
                    {fieldErrors.password}
                  </p>
                ) : null}
                <p id="password-hint" className="text-[12px] text-stone-500">
                  {PASSWORD_RULE_HINT}
                </p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="password-confirm" className="text-[14px] text-stone-600">
                  비밀번호 확인
                </Label>
                <Input
                  id="password-confirm"
                  type="password"
                  placeholder="비밀번호 확인"
                  autoComplete="new-password"
                  value={passwordConfirm}
                  onChange={handleFieldChange("password_confirm", setPasswordConfirm)}
                  aria-invalid={Boolean(fieldErrors.password_confirm)}
                  aria-describedby={
                    fieldErrors.password_confirm ? "password-confirm-error" : undefined
                  }
                />
                {fieldErrors.password_confirm ? (
                  <p id="password-confirm-error" className="text-[12px] text-red-500">
                    {fieldErrors.password_confirm}
                  </p>
                ) : null}
              </div>

              <div className="space-y-2">
                <Label htmlFor="church" className="text-[14px] text-stone-600">
                  교회
                </Label>
                <Input
                  id="church"
                  type="text"
                  placeholder="교회명"
                  autoComplete="organization"
                  value={church}
                  onChange={handleFieldChange("church", setChurch)}
                  aria-invalid={Boolean(fieldErrors.church)}
                  aria-describedby={fieldErrors.church ? "church-error" : undefined}
                />
                {fieldErrors.church ? (
                  <p id="church-error" className="text-[12px] text-red-500">
                    {fieldErrors.church}
                  </p>
                ) : null}
              </div>

              <div className="space-y-2">
                <Label htmlFor="church-address" className="text-[14px] text-stone-600">
                  교회주소
                </Label>
                <Input
                  id="church-address"
                  type="text"
                  placeholder="교회 주소"
                  autoComplete="street-address"
                  value={churchAddress}
                  onChange={handleFieldChange("church_address", setChurchAddress)}
                  aria-invalid={Boolean(fieldErrors.church_address)}
                  aria-describedby={fieldErrors.church_address ? "church-address-error" : undefined}
                />
                {fieldErrors.church_address ? (
                  <p id="church-address-error" className="text-[12px] text-red-500">
                    {fieldErrors.church_address}
                  </p>
                ) : null}
              </div>

              <div className="space-y-2">
                <Label htmlFor="phone" className="text-[14px] text-stone-600">
                  휴대폰 번호
                </Label>
                <Input
                  id="phone"
                  type="tel"
                  placeholder="010-1234-5678"
                  autoComplete="tel"
                  value={phone}
                  onChange={handleFieldChange("phone", setPhone)}
                  aria-invalid={Boolean(fieldErrors.phone)}
                  aria-describedby={fieldErrors.phone ? "phone-error" : undefined}
                />
                {fieldErrors.phone ? (
                  <p id="phone-error" className="text-[12px] text-red-500">
                    {fieldErrors.phone}
                  </p>
                ) : null}
              </div>

              <div className="space-y-2">
                <label className="flex items-start gap-2 text-[12px] text-stone-600">
                  <input
                    type="checkbox"
                    className="mt-[2px] h-4 w-4 rounded border-stone-300"
                    checked={agreed}
                    onChange={handleAgreedChange}
                    aria-invalid={Boolean(fieldErrors.agreed_terms)}
                    aria-describedby={fieldErrors.agreed_terms ? "agreed-terms-error" : undefined}
                  />
                  <span>서비스 이용약관 및 개인정보 수집·이용에 동의합니다.</span>
                </label>
                {fieldErrors.agreed_terms ? (
                  <p id="agreed-terms-error" className="text-[12px] text-red-500">
                    {fieldErrors.agreed_terms}
                  </p>
                ) : null}
              </div>

              {alertMessage ? (
                <Alert variant="destructive">
                  <AlertTitle>회원가입 실패</AlertTitle>
                  <AlertDescription>{alertMessage}</AlertDescription>
                </Alert>
              ) : null}

              <Button type="submit" className="mt-4 w-full" disabled={isSubmitting}>
                {isSubmitting ? "회원가입 중..." : "회원가입"}
              </Button>
            </form>

            <p className="mt-4 text-center text-[12px] text-stone-500">
              이미 계정이 있으신가요?{" "}
              <Link to="/login" className="font-medium text-stone-700 underline underline-offset-2">
                로그인
              </Link>
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
