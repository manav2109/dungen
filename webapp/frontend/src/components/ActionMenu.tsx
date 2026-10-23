import { useEffect, useRef } from "react";
import Icon from "./Icon";

/** Native disclosure: normal tab navigation, outside-click and Escape dismissal. */
export default function ActionMenu({ label, children, className = "", ariaLabel }: {
  label: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  ariaLabel?: string;
}) {
  const ref = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const dismiss = (event: PointerEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) ref.current.open = false;
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && ref.current?.open && ref.current.contains(event.target as Node)) {
        event.preventDefault();
        event.stopPropagation();
        ref.current.open = false;
        ref.current.querySelector("summary")?.focus();
      }
    };
    document.addEventListener("pointerdown", dismiss);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", dismiss);
      document.removeEventListener("keydown", escape);
    };
  }, []);
  return (
    <details ref={ref} className={`action-menu ${className}`}>
      <summary className="btn" aria-label={ariaLabel}>{label}<Icon name="chevron" /></summary>
      <div className="action-menu-content" onClick={(event) => {
        if ((event.target as Element).closest("button:not(:disabled)") && ref.current) ref.current.open = false;
      }}>{children}</div>
    </details>
  );
}
