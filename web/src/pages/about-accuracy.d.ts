// The accuracy cards bench/accuracy/summary.py writes beside this file; the About page loads them in their own chunk.
declare module "*/accuracy-data.js" {
  export const CARDS: { id: string; title: string; claim: string; rows: [string, string, string][]; weak: string; labeller: string; link: string }[];
}
