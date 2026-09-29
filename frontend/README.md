# Live Office (frontend)

A 3D office where the AI workforce works in real time. Employees sleep at their desks until a Lead hands them a note. Every handoff is a character walking the note across the floor.

- React 18 + TypeScript + Vite, Three.js for the office, Tailwind v4 + framer-motion for the UI.
- Talks to the backend in `workforce/` (REST + Server-Sent Events). The API is documented in `docs/STITCH-HANDOFF.md`, Part 2.
- With no backend connected, it runs a **demo feed**: an in-browser copy of the backend's event flow (`src/lib/demoFeed.ts`).

## Run

```bash
npm install
npm run dev        # http://localhost:5173
npm run build      # typecheck + production build in dist/
```

To use your real office, click the status pill at the top, then **Connect backend**, and enter the backend URL and its `WORKFORCE_API_TOKEN`. The backend needs `WORKFORCE_FRONTEND_ORIGIN` set to this site's origin (CORS). The URL and token are stored in this browser only.

## How it fits together

| File | Job |
|---|---|
| `src/lib/liveFeed.ts` | Backend client: `/api/office`, `/api/office/state`, `/api/live` (SSE), prompt/reply/approve/commands |
| `src/lib/demoFeed.ts` | Same interface, simulated in the browser |
| `src/lib/controller.ts` | Loads the snapshot, then plays events into the 3D engine and the UI store |
| `src/lib/scheduler.ts` | Keeps animations in order: a walk holds its task, sender and receiver; unrelated tasks animate in parallel |
| `src/office/engine.ts` | The Three.js office: floor plan from `/api/office`, characters, poses, walking, notes, camera |
| `src/ui/Labels.tsx` | Name tags (hidden while asleep; shown when awake or hovered), speech bubbles |
| `src/ui/Modals.tsx` | Give a task, profile, task timeline, connect |
| `src/App.tsx` | Status pill, decision card, camera menu, activity ticker |

## Third-party components

Copied verbatim from [amicro](https://github.com/Subhan-code/Amicro--Micro-transitions-) (MIT) into `src/components/amicro/`. They are themed in the "amicro theme mapping" block at the end of `src/styles.css`; the files themselves are unedited.

| Component | Used for |
|---|---|
| `pulse-dot` | Connection dot in the status pill (green live, amber reconnecting, gold demo) |
| `dynamic-island` | Shown in the status pill while anyone is working |
| `typing-indicator` | Next to the name of an employee who is working |
| `blur-text` | Speech bubbles appearing |
| `skeleton` | While the office loads |
