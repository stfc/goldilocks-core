import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const library = vi.hoisted(() => ({
  createViewer: vi.fn(),
  releaseListeners: [] as (() => void)[],
  resize: vi.fn(),
  mouseup: vi.fn(),
  touchend: vi.fn(),
}));

vi.mock("3dmol", () => ({ createViewer: library.createViewer }));

beforeEach(() => {
  // Exercise a fresh document-lifetime adapter for each independent scenario.
  vi.clearAllMocks();
  vi.resetModules();
  library.createViewer.mockImplementation((element: HTMLElement) => {
    element.append(document.createElement("canvas"));
    // Model the library's non-disposable global listeners, not clear() as a destructor.
    for (const [target, event, handler] of [
      [window, "resize", library.resize],
      [document.body, "mouseup", library.mouseup],
      [document.body, "touchend", library.touchend],
    ] as const) {
      const listener = () => {
        handler();
      };
      target.addEventListener(event, listener);
      library.releaseListeners.push(() => {
        target.removeEventListener(event, listener);
      });
    }
    return {
      clear: vi.fn(),
      resize: vi.fn(),
      render: vi.fn(),
      setBackgroundColor: vi.fn(),
      addModel: vi.fn(),
      setStyle: vi.fn(),
      addUnitCell: vi.fn(),
      zoomTo: vi.fn(),
    };
  });
});

afterEach(() => {
  for (const release of library.releaseListeners.splice(0)) release();
});

describe("structure viewer adapter", () => {
  it("reuses the same canvas and global handlers through navigation and theme changes", async () => {
    const { attachStructureViewer } =
      await import("../../src/viewer/structureViewer");
    const host = document.createElement("div");
    const first = await attachStructureViewer(
      host,
      new AbortController().signal,
    );
    const canvas = host.querySelector("canvas");
    first.dispose();
    for (let cycle = 0; cycle < 5; cycle += 1) {
      const viewer = await attachStructureViewer(
        host,
        new AbortController().signal,
      );
      viewer.refreshTheme();
      viewer.show("data_Si");
      expect(host.querySelector("canvas")).toBe(canvas);
      viewer.dispose();
      expect(host).toBeEmptyDOMElement();
    }
    window.dispatchEvent(new Event("resize"));
    document.body.dispatchEvent(new Event("mouseup"));
    document.body.dispatchEvent(new Event("touchend"));
    expect(library.resize).toHaveBeenCalledOnce();
    expect(library.mouseup).toHaveBeenCalledOnce();
    expect(library.touchend).toHaveBeenCalledOnce();
  });

  it("does not erase a replacement viewer when an obsolete lease disposes", async () => {
    const { attachStructureViewer } =
      await import("../../src/viewer/structureViewer");
    const oldHost = document.createElement("div");
    const newHost = document.createElement("div");
    const obsolete = await attachStructureViewer(
      oldHost,
      new AbortController().signal,
    );
    const canvas = oldHost.querySelector("canvas");
    const current = await attachStructureViewer(
      newHost,
      new AbortController().signal,
    );
    obsolete.dispose();
    expect(oldHost).toBeEmptyDOMElement();
    expect(newHost.querySelector("canvas")).toBe(canvas);
    current.dispose();
    expect(newHost).toBeEmptyDOMElement();
  });

  it("does not attach a viewer when cancelled during library loading", async () => {
    const { attachStructureViewer } =
      await import("../../src/viewer/structureViewer");
    const host = document.createElement("div");
    const lifetime = new AbortController();
    const pending = attachStructureViewer(host, lifetime.signal);
    lifetime.abort();
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
    expect(host).toBeEmptyDOMElement();
    expect(library.createViewer).not.toHaveBeenCalled();
  });

  it("leaves no surface after initialization failure and permits a retry", async () => {
    const { attachStructureViewer } =
      await import("../../src/viewer/structureViewer");
    library.createViewer.mockImplementationOnce(() => {
      throw new Error("WebGL is unavailable");
    });
    const host = document.createElement("div");
    await expect(
      attachStructureViewer(host, new AbortController().signal),
    ).rejects.toThrow("WebGL is unavailable");
    expect(host).toBeEmptyDOMElement();
    const viewer = await attachStructureViewer(
      host,
      new AbortController().signal,
    );
    expect(host).toContainElement(host.querySelector("canvas"));
    viewer.dispose();
  });
});
