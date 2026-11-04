import { describe, expect, it } from "vitest";

import { formatSiteCount } from "../../src/viewer/siteCount";

describe("formatSiteCount", () => {
  it("uses the singular noun for a one-site cell", () => {
    expect(formatSiteCount(1, "atomic site")).toBe("1 atomic site");
    expect(formatSiteCount(1, "site")).toBe("1 site");
  });

  it("uses the plural noun for any other count", () => {
    expect(formatSiteCount(2, "atomic site")).toBe("2 atomic sites");
    expect(formatSiteCount(8, "atomic site")).toBe("8 atomic sites");
    expect(formatSiteCount(10, "site")).toBe("10 sites");
  });
});
