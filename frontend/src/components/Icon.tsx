// Kleine Inline-SVG-Symbole (Strichzeichnungen, 24er Raster), damit keine Icon-Bibliothek noetig ist
const PATHS: Record<string, string> = {
  dashboard: "M3 13h8V3H3zm10 8h8V11h-8zM3 21h8v-6H3zm10-18v6h8V3z",
  alert: "M12 9v4m0 4h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z",
  server: "M4 4h16v6H4zm0 10h16v6H4zM8 7h.01M8 17h.01",
  network: "M12 3v6m0 0H6v4m6-4h6v4M4 13h4v4H4zm6 0h4v4h-4zm6 0h4v4h-4zM10 3h4v4h-4z",
  users: "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2m7-10a4 4 0 1 0 0-8 4 4 0 0 0 0 8zm13 10v-2a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8",
  user: "M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2m8-10a4 4 0 1 0 0-8 4 4 0 0 0 0 8z",
  logout: "M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4m7 14 5-5-5-5m5 5H9",
  sun: "M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10zm0-16v2m0 18v2M4.2 4.2l1.4 1.4m12.8 12.8 1.4 1.4M1 12h2m18 0h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4",
  moon: "M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z",
  plus: "M12 5v14m-7-7h14",
  edit: "M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z",
  trash: "M3 6h18m-2 0-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6m5 5v6m4-6v6M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2",
  check: "M20 6 9 17l-5-5",
  x: "M18 6 6 18M6 6l12 12",
  circle: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z",
  checkCircle: "M22 11.1V12a10 10 0 1 1-5.9-9.1M22 4 12 14l-3-3",
  xCircle: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zm3-13-6 6m0-6 6 6",
  help: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zm-2.1-13a3 3 0 0 1 5.8 1c0 2-3 3-3 3m.1 4h.01",
  refresh: "M23 4v6h-6M1 20v-6h6m14.5-5A9 9 0 0 0 5.6 5.6L1 10m22 4-4.6 4.4A9 9 0 0 1 3.5 15",
  key: "M21 2l-2 2m-7.6 7.6a5.5 5.5 0 1 1-7.8 7.8 5.5 5.5 0 0 1 7.8-7.8zm0 0L15.5 7.5m0 0 3 3L22 7l-3-3m-3.5 3.5L19 4",
  arrowLeft: "M19 12H5m7 7-7-7 7-7",
};

export type IconName = keyof typeof PATHS;

export function Icon({ name, size = 16, title }: { name: IconName; size?: number; title?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden={title ? undefined : true}
      role={title ? "img" : undefined}
      style={{ flex: "none" }}
    >
      {title && <title>{title}</title>}
      <path d={PATHS[name]} />
    </svg>
  );
}
