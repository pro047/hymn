// Type-only shim for input.jsx. TypeScript infers destructured JS props as
// *required*, which makes every call site fail; a co-located .d.ts wins over
// the .jsx during resolution. Delete this file when the component becomes .tsx.
import type { ComponentProps, ReactElement } from "react";

declare function Input(props: ComponentProps<"input">): ReactElement;

export { Input };
