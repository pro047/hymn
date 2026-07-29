// Type-only shim for alert.jsx — see input.d.ts for why.
import type { ComponentProps, ReactElement } from "react";

declare function Alert(
  props: ComponentProps<"div"> & { variant?: "default" | "destructive" }
): ReactElement;
declare function AlertTitle(props: ComponentProps<"h5">): ReactElement;
declare function AlertDescription(props: ComponentProps<"div">): ReactElement;

export { Alert, AlertTitle, AlertDescription };
