// Entry: styles, then the app shell. Pages and uPlot load later, when first opened.
import "./styles/index.css";
import { render } from "preact";
import { App } from "./app/App";

render(<App />, document.getElementById("root")!);
