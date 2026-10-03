declare global {
  interface Window {
    umami?: {
      track(name: string, data: Record<string, string>): Promise<unknown>;
    };
  }
}

export function trackEvent(name: string, data: Record<string, string> = {}) {
  try {
    void window.umami?.track(name, {
      locale: document.documentElement.lang,
      ...data,
    }).catch(() => {});
  } catch {
    // Analytics must not interrupt a successful user action.
  }
}
