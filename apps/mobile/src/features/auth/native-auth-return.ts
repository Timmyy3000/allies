type NativeAuthReturnListener = (url: string) => void;

let activeListener: NativeAuthReturnListener | null = null;

export function registerNativeAuthReturnListener(listener: NativeAuthReturnListener): () => void {
  activeListener = listener;
  return () => {
    if (activeListener === listener) activeListener = null;
  };
}

export function deliverNativeAuthReturn(url: string): boolean {
  if (!activeListener) return false;
  activeListener(url);
  return true;
}
