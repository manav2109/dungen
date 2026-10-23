type IconName = "upload" | "plus" | "download" | "chevron" | "cursor" | "connect" | "undo" | "redo" | "layout" | "search" | "user";

const paths: Record<IconName, React.ReactNode> = {
  upload: <><path d="M12 16V3m-5 5 5-5 5 5" /><path d="M4 15v5h16v-5" /></>,
  plus: <path d="M12 5v14M5 12h14" />,
  download: <><path d="M12 3v13m-5-5 5 5 5-5" /><path d="M4 16v4h16v-4" /></>,
  chevron: <path d="m7 10 5 5 5-5" />,
  cursor: <path d="m5 3 14 9-7 2-3 7-4-18Z" />,
  connect: <><rect x="3" y="3" width="6" height="6" rx="1" /><rect x="15" y="15" width="6" height="6" rx="1" /><path d="M9 6h9v9" /></>,
  undo: <><path d="m8 4-5 5 5 5" /><path d="M3 9h10a7 7 0 0 1 0 14" /></>,
  redo: <><path d="m16 4 5 5-5 5" /><path d="M21 9H11a7 7 0 0 0 0 14" /></>,
  layout: <><rect x="8" y="2" width="8" height="6" rx="1" /><rect x="2" y="16" width="7" height="6" rx="1" /><rect x="15" y="16" width="7" height="6" rx="1" /><path d="M12 8v4M5.5 16v-4h13v4" /></>,
  search: <><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 5 5" /></>,
  user: <><circle cx="12" cy="8" r="4" /><path d="M4 21v-2a8 8 0 0 1 16 0v2" /></>,
};

export default function Icon({ name }: { name: IconName }) {
  return <svg className="ui-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}
