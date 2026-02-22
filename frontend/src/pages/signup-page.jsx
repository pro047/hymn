import { useState } from "react";
import { Link } from "react-router-dom";

import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";

export default function SignupPage() {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [church, setChurch] = useState("");
  const [churchAddress, setChurchAddress] = useState("");
  const [phone, setPhone] = useState("");
  const [agreed, setAgreed] = useState(false);

  const passwordRule = /^(?=.*[a-z])(?=.*[A-Z])[A-Za-z]{8,16}$/;
  const isPasswordValid = passwordRule.test(password);
  const isPasswordConfirmValid = passwordConfirm.length > 0 && password === passwordConfirm;

  const canSubmit =
    name.trim() &&
    email.trim() &&
    password &&
    passwordConfirm &&
    church.trim() &&
    churchAddress.trim() &&
    phone.trim() &&
    agreed &&
    isPasswordValid &&
    isPasswordConfirmValid;

  return (
    <div className="flex min-h-screen items-center justify-center bg-white px-4 text-stone-900 sm:px-6 lg:px-8">
      <div className="mx-auto w-full max-w-md">
        <Card className="border-stone-200">
          <CardContent className="pt-6">
            <p className="mb-4 text-center text-lg font-normal text-stone-300">
              H Y M N
            </p>
            <form
              className="space-y-4"
              onSubmit={(event) => event.preventDefault()}
            >
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
                  onChange={(event) => setName(event.target.value)}
                />
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
                    onChange={(event) => setEmail(event.target.value)}
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
              </div>

              <div className="space-y-2">
                <Label htmlFor="password" className="text-[14px] text-stone-600">
                  비밀번호
                </Label>
                <Input
                  id="password"
                  type="password"
                  placeholder="8 - 16 글자 영문 대,소문자"
                  autoComplete="new-password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                />
                {password.length > 0 && !isPasswordValid ? (
                  <p className="text-[12px] text-red-500">
                    비밀번호는 8~16자 영문이며 대문자/소문자를 모두 포함해야 합니다.
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
                />
                {passwordConfirm.length > 0 && !isPasswordConfirmValid ? (
                  <p className="text-[12px] text-red-500">비밀번호가 일치하지 않습니다.</p>
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
                  onChange={(event) => setChurch(event.target.value)}
                />
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
                  onChange={(event) => setChurchAddress(event.target.value)}
                />
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
                  onChange={(event) => setPhone(event.target.value)}
                />
              </div>

              <label className="flex items-start gap-2 text-[12px] text-stone-600">
                <input
                  type="checkbox"
                  className="mt-[2px] h-4 w-4 rounded border-stone-300"
                  checked={agreed}
                  onChange={(event) => setAgreed(event.target.checked)}
                />
                <span>서비스 이용약관 및 개인정보 수집·이용에 동의합니다.</span>
              </label>

              <Button
                type="submit"
                className="mt-4 w-full"
                disabled={!canSubmit}
              >
                회원가입
              </Button>
            </form>

            <p className="mt-4 text-center text-[12px] text-stone-500">
              이미 계정이 있으신가요?{" "}
              <Link
                to="/login"
                className="font-medium text-stone-700 underline underline-offset-2"
              >
                로그인
              </Link>
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
