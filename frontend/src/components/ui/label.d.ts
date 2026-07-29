// Type-only shim for label.jsx — see input.d.ts for why.
import type { ComponentProps, ReactElement } from "react";

declare function Label(props: ComponentProps<"label">): ReactElement;

export { Label };
