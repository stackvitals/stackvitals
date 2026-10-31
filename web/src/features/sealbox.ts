// libsodium's sealed box, the format GitHub's secrets API takes; its own chunk, loaded only when a secret is saved.
import { seal } from "tweetnacl-sealedbox-js";

export { seal };
