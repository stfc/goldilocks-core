import { describe, expect, it, vi } from "vitest";

import { attachStructureViewer } from "./structureViewer";

describe("structure viewer adapter", () => {
  it("rejects unavailable WebGL instead of leaving an empty canvas", () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);

    expect(() => attachStructureViewer(document.createElement("div"))).toThrow(
      "WebGL is unavailable",
    );
  });
});
