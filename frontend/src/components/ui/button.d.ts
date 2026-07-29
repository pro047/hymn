// Type-only shim for button.jsx — see input.d.ts for why.
import type { ComponentProps, ReactElement } from "react";

declare function Button(
  props: ComponentProps<"button"> & {
    variant?: "default" | "outline" | "ghost";
    size?: "default" | "sm" | "icon";
    asChild?: boolean;
  }
): ReactElement;

declare function buttonVariants(options?: {
  variant?: "default" | "outline" | "ghost";
  size?: "default" | "sm" | "icon";
  className?: string;
}): string;

export { Button, buttonVariants };
