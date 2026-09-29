import { useEffect, useRef } from "react";
import { BlurText } from "../components/amicro/blur-text";
import { TypingIndicator } from "../components/amicro/typing-indicator";
import { useStore } from "../lib/store";
import type { Employee } from "../lib/types";
import type { OfficeEngine } from "../office/engine";

const STATE_TEXT: Record<string, string> = {
  sleeping: "asleep", working: "working", supervising: "supervising", waiting_owner: "needs you",
  blocked: "blocked", paused: "paused", walking: "walking a note", owner: "you",
};

/** Name tags over each character. The engine moves them every frame through `labelSink`. */
export function Labels({ engine }: { engine: OfficeEngine | null }) {
  const office = useStore((s) => s.office);
  const els = useRef(new Map<string, HTMLElement>());

  useEffect(() => {
    if (!engine) return;
    engine.labelSink = (key, x, y, vis) => {
      const el = els.current.get(key);
      if (!el) return;
      el.style.display = vis ? "" : "none";
      el.style.transform = `translate(${x}px, ${y}px) translate(-50%, -100%)`;
    };
  }, [engine]);

  if (!office) return null;
  const people: Employee[] = [...Object.values(office.core), ...office.departments.flatMap((d) => [d.lead, ...d.specialists])];
  const ref = (key: string) => (el: HTMLElement | null) => { if (el) els.current.set(key, el); else els.current.delete(key); };

  return (
    <div className="labels">
      {people.map((e) => <Tag key={e.id} emp={e} setRef={ref(e.id)} />)}
      <Tag emp={{ id: "owner", name: "You", kind: "lead", department: "owner", role: [], promptable: false }} setRef={ref("owner")} owner />
    </div>
  );
}

function Tag({ emp, setRef, owner }: { emp: Employee; setRef: (el: HTMLElement | null) => void; owner?: boolean }) {
  const p = useStore((s) => s.presence[emp.id]);
  const walking = useStore((s) => !!s.walking[emp.id]);
  const hovered = useStore((s) => s.hovered === emp.id);
  const bubble = useStore((s) => s.bubbles[emp.id]);
  const state = walking ? "walking" : owner ? "owner" : p?.state ?? "sleeping";
  const asleep = state === "sleeping" || state === "paused";
  const show = hovered || !asleep || !!bubble;   // sleeping people show only a small zZ
  const lead = emp.kind === "lead" || emp.kind === "router";
  return (
    <div ref={setRef} className={"lbl" + (lead && !owner ? " lead" : "")} data-s={state} data-show={show} data-hover={hovered}>
      {bubble && (
        <span className="bub">
          {/* amicro BlurText re-animates per message via key */}
          <BlurText key={bubble.id} text={bubble.text} duration={0.35} staggerDelay={0.008} />
        </span>
      )}
      {asleep && !hovered && <span className="zz" aria-hidden="true">zZ</span>}
      {show && (
        <span className="nm">
          <i />{emp.name}
          {state === "working" && <span className="amicro-typing"><TypingIndicator /></span>}
        </span>
      )}
      {hovered && <span className="st">{state === "working" && p?.phase ? `working: ${p.phase}` : STATE_TEXT[state] ?? state}</span>}
    </div>
  );
}
