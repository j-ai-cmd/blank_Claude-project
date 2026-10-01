import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/** shadcn's class-name helper, required by the smoothui components (`@/lib/utils`). */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
