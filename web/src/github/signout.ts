// Modules holding a token of their own (the pasted one, each repo's) register here to forget it on sign-out.
// The set sits on a shared global so data/write.ts can join without importing anything.
const forgetters = (): Set<() => void> => ((globalThis as any)[Symbol.for("sv.signout")] ??= new Set<() => void>());

export const onSignOut = (fn: () => void): void => { forgetters().add(fn); };

export function forgetAll(): void {
  forgetters().forEach((fn) => { try { fn(); } catch { /* keep going */ } });
}
