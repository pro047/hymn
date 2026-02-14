import { cva } from "class-variance-authority"

import { cn } from "../../lib/utils"

const alertVariants = cva("relative w-full rounded-lg border p-4", {
  variants: {
    variant: {
      default: "bg-white text-stone-950",
      destructive: "border-red-200/70 bg-red-50 text-red-900",
    },
  },
  defaultVariants: {
    variant: "default",
  },
})

function Alert({ className, variant, ...props }) {
  return <div role="alert" className={cn(alertVariants({ variant }), className)} {...props} />
}

function AlertTitle({ className, ...props }) {
  return <h5 className={cn("mb-1 font-medium leading-none tracking-tight", className)} {...props} />
}

function AlertDescription({ className, ...props }) {
  return <div className={cn("text-sm", className)} {...props} />
}

export { Alert, AlertTitle, AlertDescription }
