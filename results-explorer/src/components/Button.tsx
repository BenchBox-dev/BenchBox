import type { ComponentChildren, JSX } from "preact";

export type ButtonVariant = "primary" | "secondary" | "subtle" | "danger";

// Preact convention: callers pass `class` (not `className`). Omitting both
// `size` (we redefine it) and `className` (avoids two ways to spell the same
// prop) keeps the surface area small and unambiguous.
type NativeButtonProps = Omit<JSX.IntrinsicElements["button"], "size" | "className">;

interface ButtonProps extends NativeButtonProps {
  variant?: ButtonVariant;
  size?: "sm" | "md";
  iconOnly?: boolean;
  children: ComponentChildren;
}

const SIZE_CLASS = {
  sm: "px-3 py-1.5 text-xs",
  md: "px-4 py-2 text-sm",
} as const;

export function Button({
  variant = "primary",
  size = "md",
  iconOnly = false,
  class: extraClass = "",
  disabled,
  onClick,
  children,
  ...rest
}: ButtonProps) {
  const variantClass = `btn-${variant}`;
  const sizeClass = iconOnly ? "p-1.5" : SIZE_CLASS[size];
  const composed = [variantClass, sizeClass, extraClass].filter(Boolean).join(" ");
  return (
    <button
      {...rest}
      disabled={disabled}
      aria-disabled={disabled || undefined}
      onClick={disabled ? undefined : onClick}
      class={composed}
    >
      {children}
    </button>
  );
}

export default Button;
