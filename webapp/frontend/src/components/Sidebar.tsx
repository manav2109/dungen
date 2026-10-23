import { useCallback, useEffect, useRef } from "react";

export const SIDEBAR_MIN = 260;
export const SIDEBAR_MAX = 640;
export const SIDEBAR_DEFAULT = 340;

interface Props<T extends string> {
  tabs: [T, string, React.ReactNode][]; // [key, full label, icon for the collapsed rail]
  groups?: { label: string; keys: T[] }[];
  tab: T;
  onTabChange: (t: T) => void;
  width: number;
  onWidthChange: (w: number) => void;
  collapsed: boolean;
  onSetCollapsed: (c: boolean) => void;
  children: React.ReactNode;
}

export default function Sidebar<T extends string>({
  tabs,
  groups,
  tab,
  onTabChange,
  width,
  onWidthChange,
  collapsed,
  onSetCollapsed,
  children,
}: Props<T>) {
  const dragging = useRef(false);
  const navigation = groups || tabs.map(([key, label]) => ({ label, keys: [key] }));
  const activeGroup = navigation.find((group) => group.keys.includes(tab));

  const onPointerMove = useCallback(
    (ev: PointerEvent) => {
      if (!dragging.current) return;
      // The sidebar is docked right, so its width is whatever is left between the
      // pointer and the window's right edge.
      const next = Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, window.innerWidth - ev.clientX));
      onWidthChange(next);
    },
    [onWidthChange]
  );

  const stopDrag = useCallback(() => {
    if (!dragging.current) return;
    dragging.current = false;
    document.body.classList.remove("resizing-col");
  }, []);

  useEffect(() => {
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", stopDrag);
    window.addEventListener("pointercancel", stopDrag);
    return () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", stopDrag);
      window.removeEventListener("pointercancel", stopDrag);
      document.body.classList.remove("resizing-col");
    };
  }, [onPointerMove, stopDrag]);

  const startDrag = (ev: React.PointerEvent) => {
    ev.preventDefault();
    dragging.current = true;
    // Suppress text selection and keep the resize cursor while dragging over the canvas.
    document.body.classList.add("resizing-col");
  };

  if (collapsed) {
    return (
      <aside className="sidebar-rail">
        <button
          className="rail-toggle"
          onClick={() => onSetCollapsed(false)}
          title="Expand panel"
          aria-label="Expand panel"
          aria-expanded={false}
        >
          ‹
        </button>
        {navigation.map((group) => {
          const [key, , icon] = tabs.find(([key]) => key === group.keys[0])!;
          return (
          <button
            key={group.label}
            className={`rail-tab ${group.keys.includes(tab) ? "active" : ""}`}
            title={group.label}
            aria-label={group.label}
            aria-pressed={group.keys.includes(tab)}
            onClick={() => {
              onTabChange(group.keys.includes(tab) ? tab : key);
              onSetCollapsed(false);
            }}
          >
            {icon}
          </button>
        ); })}
      </aside>
    );
  }

  return (
    <aside className="sidebar" style={{ width }}>
      <div
        className="sidebar-resizer"
        onPointerDown={startDrag}
        onDoubleClick={() => onWidthChange(SIDEBAR_DEFAULT)}
        role="separator"
        tabIndex={0}
        aria-valuemin={SIDEBAR_MIN}
        aria-valuemax={SIDEBAR_MAX}
        aria-valuenow={width}
        onKeyDown={(event) => {
          if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
            event.preventDefault();
            onWidthChange(Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, width + (event.key === "ArrowLeft" ? 20 : -20))));
          } else if (event.key === "Home") {
            event.preventDefault();
            onWidthChange(SIDEBAR_DEFAULT);
          }
        }}
        aria-orientation="vertical"
        aria-label="Resize panel (double-click to reset)"
        title="Drag to resize · double-click to reset"
      />
      <div className="sidebar-head">
        <div className="sidebar-heading"><span className="eyebrow">Workspace</span><h2>{activeGroup?.label}</h2></div>
        <button
          className="rail-toggle"
          onClick={() => onSetCollapsed(true)}
          title="Collapse panel"
          aria-label="Collapse panel"
          aria-expanded
        >
          ›
        </button>
      </div>
      <nav className="sidebar-nav" aria-label="Workspace panels">
        {navigation.map((group) => {
          const active = group.keys.includes(tab);
          const primary = tabs.find(([key]) => key === group.keys[0]);
          return <button key={group.label} className={active ? "active" : ""} aria-pressed={active} onClick={() => onTabChange(active ? tab : group.keys[0])} title={group.label}>{primary?.[2]}<span>{group.label}</span></button>;
        })}
      </nav>
      {groups && (activeGroup?.keys.length || 0) > 1 && <div className="panel-subnav" role="group" aria-label="Panel tools">
          {tabs.filter(([key]) => activeGroup?.keys.includes(key)).map(([key, label]) => (
            <button
              key={key}
              className={tab === key ? "active" : ""}
              onClick={() => onTabChange(key)}
              aria-pressed={tab === key}
            >
              {label}
            </button>
          ))}
      </div>}
      <div className="sidebar-body">{children}</div>
    </aside>
  );
}
