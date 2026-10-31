// A plain line diff (longest common subsequence), for showing what setup would change in a file that is already there.
export type DiffLine = { op: " " | "+" | "-"; text: string };

export function lineDiff(before: string, after: string): DiffLine[] {
  const a = before.split(/\r?\n/), b = after.split(/\r?\n/);
  // Files here are a few hundred lines at most; past that, show it as replaced whole.
  if (a.length * b.length > 4_000_000) return [...a.map((text) => ({ op: "-" as const, text })), ...b.map((text) => ({ op: "+" as const, text }))];
  const n = a.length, m = b.length;
  const L: Uint32Array[] = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) L[i]![j] = a[i] === b[j] ? L[i + 1]![j + 1]! + 1 : Math.max(L[i + 1]![j]!, L[i]![j + 1]!);
  const out: DiffLine[] = [];
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) { out.push({ op: " ", text: a[i]! }); i++; j++; }
    else if (L[i + 1]![j]! >= L[i]![j + 1]!) out.push({ op: "-", text: a[i++]! });
    else out.push({ op: "+", text: b[j++]! });
  }
  while (i < n) out.push({ op: "-", text: a[i++]! });
  while (j < m) out.push({ op: "+", text: b[j++]! });
  return out;
}

// The changed lines with `context` unchanged lines around each change, as unified-diff-like text.
export function diffText(lines: DiffLine[], context = 2): string {
  const keep = lines.map((l, k) => l.op !== " " || lines.slice(Math.max(0, k - context), k + context + 1).some((x) => x.op !== " "));
  const out: string[] = [];
  lines.forEach((l, k) => {
    if (keep[k]) out.push(`${l.op} ${l.text}`);
    else if (k === 0 || keep[k - 1]) out.push("  …");
  });
  return out.join("\n");
}
