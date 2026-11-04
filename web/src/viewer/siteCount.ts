/** Returns a structure's site count with `noun`, in the plural unless the
 * count is 1: "1 atomic site", "8 atomic sites", "1 site", "8 sites". */
export function formatSiteCount(
  count: number,
  noun: "site" | "atomic site",
): string {
  return `${String(count)} ${noun}${count === 1 ? "" : "s"}`;
}
