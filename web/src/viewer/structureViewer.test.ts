import { describe, expect, it, vi } from "vitest";

import { attachStructureViewer } from "./structureViewer";

describe("structure viewer adapter", () => {
  it("rejects unavailable WebGL instead of leaving an empty canvas", async () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);

    await expect(
      attachStructureViewer(document.createElement("div")),
    ).rejects.toThrow("WebGL is unavailable");
  });
});
