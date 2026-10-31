// A tiny observable value with a hook, so app state needs no context providers (sheets render in their own roots).
import { useEffect, useState } from "preact/hooks";

export interface Store<T> { get(): T; set(v: T | ((old: T) => T)): void; subscribe(fn: (v: T) => void): () => void }

export function store<T>(initial: T): Store<T> {
  let value = initial;
  const subs = new Set<(v: T) => void>();
  return {
    get: () => value,
    set(v) {
      const next = typeof v === "function" ? (v as (old: T) => T)(value) : v;
      if (Object.is(next, value)) return;
      value = next;
      subs.forEach((fn) => fn(value));
    },
    subscribe(fn) { subs.add(fn); return () => { subs.delete(fn); }; },
  };
}

export function useStore<T>(s: Store<T>): T {
  const [, force] = useState(0);
  useEffect(() => s.subscribe(() => force((n) => n + 1)), [s]);
  return s.get();
}

// Per-viewer conveniences; storage can be missing or refuse, and the app works without it.
export const prefs = {
  get<T>(key: string, fallback: T): T {
    try { const v = localStorage.getItem("sv:" + key); return v === null ? fallback : (JSON.parse(v) as T); } catch { return fallback; }
  },
  set(key: string, value: unknown): void {
    try { localStorage.setItem("sv:" + key, JSON.stringify(value)); } catch { /* private window: this visit only */ }
  },
};
