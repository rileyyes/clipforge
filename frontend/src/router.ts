export type Route = { page: string; id?: string };

export function parseHash(h: string): Route {
  const [page = "dashboard", id] = h.replace(/^#\/?/, "").split("/");
  return { page: page || "dashboard", id };
}

export const go = (path: string) => { window.location.hash = "#/" + path; };
