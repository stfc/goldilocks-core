import { describe, expect, it, vi } from "vitest";

import { attachStructureViewer } from "../../src/viewer/structureViewer";

vi.mock("3dmol", () => ({
  createViewer: (element: HTMLElement) => {
    element.append(document.createElement("canvas"));
    return { clear: vi.fn(), resize: vi.fn(), render: vi.fn() };
  },
}));

describe("structure viewer adapter", () => {
  it("does not erase a replacement viewer when an obsolete viewer disposes", async () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(
      {} as WebGLRenderingContext,
    );
    vi.stubGlobal(
      "ResizeObserver",
      class {
        observe = vi.fn();
        disconnect = vi.fn();
      },
    );
    const host = document.createElement("div");
    try {
      const [obsolete, current] = await Promise.all([
        attachStructureViewer(host),
        attachStructureViewer(host),
      ]);
      const replacement = host.querySelectorAll("canvas")[1];
      obsolete.dispose();
      expect(host.querySelectorAll("canvas")).toHaveLength(1);
      expect(host).toContainElement(replacement ?? null);
      current.dispose();
      expect(host).toBeEmptyDOMElement();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("rejects unavailable WebGL instead of leaving an empty canvas", async () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);

    await expect(
      attachStructureViewer(document.createElement("div")),
    ).rejects.toThrow("WebGL is unavailable");
  });
});
