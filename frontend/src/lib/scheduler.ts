/**
 * Plays events in order per resource. A walk holds its task, its sender and its receiver; anything later
 * that touches one of those waits, while unrelated tasks animate at the same time. Each key can be released
 * early (the receiver is free once the note lands; the sender only once they are back in their chair).
 */
export type Release = Record<string, () => void>;

export class KeyedQueue {
  private tails = new Map<string, Promise<void>>();

  run(keys: string[], fn: (release: Release) => Promise<void> | void): void {
    const uniq = [...new Set(keys)];
    const waits = uniq.map((k) => this.tails.get(k) ?? Promise.resolve());
    const release: Release = {};
    for (const k of uniq) {
      const p = new Promise<void>((r) => (release[k] = r));
      this.tails.set(k, p);
    }
    Promise.all(waits)
      .then(() => fn(release))
      .catch((e) => console.error("[office] event failed", e))
      .finally(() => uniq.forEach((k) => release[k]()));
  }

  clear() { this.tails.clear(); }
}
