import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/** "claude-sonnet-5-5" -> "Sonnet 5.5"; anything else is shown as given. */
export function modelLabel(id: string | null | undefined): string {
  const m = /^claude-([a-z]+)-(\d+)(?:-(\d+))?$/.exec(String(id ?? ""));
  if (!m) return String(id ?? "");
  return `${m[1][0].toUpperCase()}${m[1].slice(1)} ${m[2]}${m[3] ? "." + m[3] : ""}`;
}

/** shadcn's class-name helper, required by the smoothui components (`@/lib/utils`). */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
