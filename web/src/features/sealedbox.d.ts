// tweetnacl-sealedbox-js ships no types: seal(message, publicKey) returns ephemeral key + box.
declare module "tweetnacl-sealedbox-js" {
  export function seal(message: Uint8Array, publicKey: Uint8Array): Uint8Array;
  export function open(sealed: Uint8Array, publicKey: Uint8Array, secretKey: Uint8Array): Uint8Array | null;
  export const overheadLength: number;
}
