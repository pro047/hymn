import { useState, type ChangeEvent, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import { requestAuth } from "../api/auth";
import { API_PATHS } from "../api/paths";
import { alertMessageOf, clearFieldError, toFormError, type ApiError } from "../lib/api-error";
import { setTokens } from "../lib/auth-storage";
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
  "church",
  "church_address",
  "phone",
  "agreed_terms",
] as const;

const PASSWORD_MESSAGE =
  "비밀번호는 8~16자이며 영문 대문자와 소문자를 모두 포함해야 합니다. 숫자와 특수문자는 사용할 수 있습니다.";

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

  const passwordRule = /^(?=.*[a-z])(?=.*[A-Z]).{8,16}$/;
  const isPasswordValid = passwordRule.test(password);
  const isPasswordConfirmValid = passwordConfirm.length > 0 && password === passwordConfirm;

  const canSubmit = Boolean(
    name.trim() &&
    email.trim() &&
    password &&
    passwordConfirm &&
    church.trim() &&
    churchAddress.trim() &&
    phone.trim() &&
    agreed &&
    isPasswordValid &&
    isPasswordConfirmValid
  );

  const fieldErrors = apiError?.fieldErrors ?? {};
  const alertMessage = alertMessageOf(apiError);
  // A server complaint about the password outranks the local rule hint, which
  // the user has already satisfied by the time a submit can happen.
  const passwordMessage =
    fieldErrors.password || (password.length > 0 && !isPasswordValid ? PASSWORD_MESSAGE : "");

  const handleFieldChange =
    (field: string, setValue: (value: string) => void) =>
    (event: ChangeEvent<HTMLInputElement>) => {
      setValue(event.target.value);
      setApiError((previous) => clearFieldError(previous, field));
    };

  const handleAgreedChange = (event: ChangeEvent<HTMLInputElement>) => {
    setAgreed(event.target.checked);
    setApiError((previous) => clearFieldError(previous, "agreed_terms"));
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canSubmit || isSubmitting) return;

    setApiError(null);
    setIsSubmitting(true);

    try {
      const outcome = await requestAuth({
        url: API_PATHS.authSignup,
        body: {
          name: name.trim(),
          email: email.trim().toLowerCase(),
          password,
          church: church.trim(),
          church_address: churchAddress.trim(),
          phone: phone.trim(),
          agreed_terms: agreed,
        },
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
                <div className="flex items-center gap-2">
                  <Input
                    id="email"
                    type="email"
                    placeholder="you@church.org"
                    autoComplete="email"
                    value={email}
                    onChange={handleFieldChange("email", setEmail)}
                    aria-invalid={Boolean(fieldErrors.email)}
                    aria-describedby={fieldErrors.email ? "email-error" : undefined}
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-10 shrink-0 px-1 text-stone-600 hover:cursor-pointer hover:bg-transparent hover:text-stone-900"
                  >
                    중복확인
                  </Button>
                </div>
                {fieldErrors.email ? (
                  <p id="email-error" className="text-[12px] text-red-500">
                    {fieldErrors.email}
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
                  placeholder="8 - 16자, 영문 대소문자 포함"
                  autoComplete="new-password"
                  value={password}
                  onChange={handleFieldChange("password", setPassword)}
                  aria-invalid={Boolean(passwordMessage)}
                  aria-describedby={passwordMessage ? "password-error" : undefined}
                />
                {passwordMessage ? (
                  <p id="password-error" className="text-[12px] text-red-500">
                    {passwordMessage}
                  </p>
                ) : null}
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
                  onChange={(event) => setPasswordConfirm(event.target.value)}
                  aria-invalid={passwordConfirm.length > 0 && !isPasswordConfirmValid}
                  aria-describedby={
                    passwordConfirm.length > 0 && !isPasswordConfirmValid
                      ? "password-confirm-error"
                      : undefined
                  }
                />
                {passwordConfirm.length > 0 && !isPasswordConfirmValid ? (
                  <p id="password-confirm-error" className="text-[12px] text-red-500">
                    비밀번호가 일치하지 않습니다.
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

              <Button type="submit" className="mt-4 w-full" disabled={!canSubmit || isSubmitting}>
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
