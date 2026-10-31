// connect.css comes in as text (with { type: "text" }); the lazy code that uses it injects it.
declare module "*/connect.css" { const css: string; export default css; }
declare module "*/welcome-sheet.css" { const css: string; export default css; }
