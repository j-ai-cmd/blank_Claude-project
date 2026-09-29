import { useSyncExternalStore } from "react";
import type { Approval, ConnState, Office, Presence, TaskSummary } from "./types";

export interface FeedLine { id: number; at: string; html: string; walk?: boolean; taskId?: string | null }
export interface Bubble { id: number; text: string }
export interface UiTask extends TaskSummary { log: { at: string; html: string }[] }

export interface State {
  loading: boolean;
  error: string | null;
  conn: ConnState;
  mode: "live" | "demo";
  office: Office | null;
  presence: Record<string, { state: Presence; phase: string | null; task_id: string | null }>;
  walking: Record<string, boolean>;
  hovered: string | null;
  tasks: Record<string, UiTask>;
  approvals: Approval[];
  feed: FeedLine[];
  bubbles: Record<string, Bubble | undefined>;
  spent: number;
  budget: number;
  paused: boolean;
  speed: number;
}

let state: State = {
  loading: true, error: null, conn: "connecting", mode: "demo", office: null, presence: {}, walking: {}, hovered: null, tasks: {},
  approvals: [], feed: [], bubbles: {}, spent: 0, budget: 20, paused: false, speed: 1,
};
const subs = new Set<() => void>();

export const store = {
  get: () => state,
  set(patch: Partial<State> | ((s: State) => Partial<State>)) {
    state = { ...state, ...(typeof patch === "function" ? patch(state) : patch) };
    subs.forEach((f) => f());
  },
  subscribe(f: () => void) { subs.add(f); return () => { subs.delete(f); }; },
};

export function useStore<T>(sel: (s: State) => T): T {
  return useSyncExternalStore(store.subscribe, () => sel(state));
}
