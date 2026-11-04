import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { type CellVectors, frameUnitCell } from "../../src/viewer/cellFraming";

// The column-major cell matrix 3Dmol derives for one-atom fcc Ni
// (a = b = c = 2.4918 Å, alpha = beta = gamma = 60 degrees): a along x, b in xy.
const NI_FCC_CELL: CellVectors = [
  [2.4918, 0, 0],
  [1.2459, 2.157962, 0],
  [1.2459, 0.719321, 2.034546],
];
const CAMERA_Z = 150;

const library = vi.hoisted(() => ({
  createViewer: vi.fn(),
  releaseListeners: [] as (() => void)[],
  resize: vi.fn(),
  mouseup: vi.fn(),
  touchend: vi.fn(),
  // view follows 3Dmol's getView() layout: model translation, rotation-group z,
  // quaternion. shown is the view last drawn. The adapter must set the field
  // of view it frames with, so it starts unknown.
  camera: { view: [] as number[], shown: [] as number[], fov: Number.NaN },
  resizeObservers: [] as {
    readonly callback: () => void;
    readonly targets: Set<Element>;
  }[],
}));

vi.mock("3dmol", () => ({ createViewer: library.createViewer }));

// jsdom has no ResizeObserver; this one records its targets so a test can
// deliver a resize to the observers still watching an element.
class RecordingResizeObserver {
  readonly targets = new Set<Element>();
  constructor(readonly callback: () => void) {
    library.resizeObservers.push(this);
  }
  observe(target: Element): void {
    this.targets.add(target);
  }
  unobserve(target: Element): void {
    this.targets.delete(target);
  }
  disconnect(): void {
    this.targets.clear();
  }
}

/** Gives the element a layout size and notifies the observers watching it. */
function resizeTo(element: HTMLElement, width: number, height: number): void {
  Object.defineProperty(element, "offsetWidth", {
    configurable: true,
    value: width,
  });
  Object.defineProperty(element, "offsetHeight", {
    configurable: true,
    value: height,
  });
  for (const observer of library.resizeObservers) {
    if (observer.targets.has(element)) observer.callback();
  }
}

function observersWatching(element: Element): number {
  return library.resizeObservers.filter((observer) =>
    observer.targets.has(element),
  ).length;
}

/** The camera last drawn: model translation, perceived distance, quaternion. */
function shownCamera() {
  const [x, y, z, rotationZ, ...quaternion] = library.camera.shown;
  return {
    translation: [x, y, z],
    distance: CAMERA_Z - (rotationZ ?? Number.NaN),
    quaternion,
  };
}

/** The distance that fits the fcc cell to a canvas at the camera's field of view. */
function fittedDistance(width: number, height: number): number {
  return frameUnitCell(NI_FCC_CELL, { width, height }, library.camera.fov)
    .distance;
}

beforeEach(() => {
  // Exercise a fresh document-lifetime adapter for each independent scenario.
  vi.clearAllMocks();
  vi.resetModules();
  vi.stubGlobal("ResizeObserver", RecordingResizeObserver);
  library.resizeObservers.length = 0;
  library.camera.view = [0, 0, 0, 0, 0, 0, 0, 1];
  library.camera.shown = [];
  library.camera.fov = Number.NaN;
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
    const { camera } = library;
    const show = () => {
      camera.shown = [...camera.view];
    };
    return {
      clear: vi.fn(),
      resize: vi.fn(),
      render: vi.fn(show),
      setBackgroundColor: vi.fn(),
      addModel: vi.fn(() => ({
        getCrystData: () => ({
          matrix: { elements: Float32Array.from(NI_FCC_CELL.flat()) },
        }),
      })),
      setStyle: vi.fn(),
      addUnitCell: vi.fn(),
      // Atom-centred framing: the one atom of the fcc cell sits at the origin.
      zoomTo: vi.fn(() => {
        camera.view.splice(0, 4, 0, 0, 0, CAMERA_Z - 30);
        show();
      }),
      setCameraParameters: vi.fn(({ fov }: { readonly fov: number }) => {
        camera.fov = fov;
      }),
      getView: vi.fn(() => [...camera.view]),
      setView: vi.fn((view: number[]) => {
        camera.view = [...view];
        show();
      }),
      setPerceivedDistance: vi.fn((distance: number) => {
        camera.view[3] = CAMERA_Z - distance;
      }),
    };
  });
});

afterEach(() => {
  for (const release of library.releaseListeners.splice(0)) release();
  vi.unstubAllGlobals();
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
    const surface = host.firstElementChild as HTMLElement;
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
    expect(observersWatching(surface)).toBe(0);
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
    const surface = oldHost.firstElementChild as HTMLElement;
    const current = await attachStructureViewer(
      newHost,
      new AbortController().signal,
    );
    obsolete.dispose();
    expect(oldHost).toBeEmptyDOMElement();
    expect(newHost.querySelector("canvas")).toBe(canvas);
    expect(observersWatching(surface)).toBe(1);
    current.dispose();
    expect(newHost).toBeEmptyDOMElement();
    expect(observersWatching(surface)).toBe(0);
  });

  it("frames the whole unit cell around its centroid, not the atoms", async () => {
    const { attachStructureViewer } =
      await import("../../src/viewer/structureViewer");
    const host = document.createElement("div");
    const viewer = await attachStructureViewer(
      host,
      new AbortController().signal,
    );
    // The issue's five-column Structure card.
    resizeTo(host.firstElementChild as HTMLElement, 284, 457);
    viewer.show("data_Ni");
    // The look-at point is (a + b + c) / 2, so the model is translated by its negative.
    const shown = shownCamera();
    expect(shown.translation[0]).toBeCloseTo(-2.4918, 4);
    expect(shown.translation[1]).toBeCloseTo(-1.438642, 4);
    expect(shown.translation[2]).toBeCloseTo(-1.017273, 4);
    // The distance is fitted for the field of view the camera was given.
    expect(library.camera.fov).toBe(20);
    expect(shown.distance).toBeCloseTo(fittedDistance(284, 457), 4);
    expect(shown.quaternion).toEqual([0, 0, 0, 1]);
    viewer.dispose();
  });

  it("re-frames the cell when the surface resizes and keeps the user's rotation", async () => {
    const { attachStructureViewer } =
      await import("../../src/viewer/structureViewer");
    const host = document.createElement("div");
    const viewer = await attachStructureViewer(
      host,
      new AbortController().signal,
    );
    const surface = host.firstElementChild as HTMLElement;
    resizeTo(surface, 417, 457);
    viewer.show("data_Ni");
    // The user rotates the cell, then a fifth grid column narrows the card.
    const rotation = [0.5, 0.5, 0.5, 0.5];
    library.camera.view.splice(4, 4, ...rotation);
    resizeTo(surface, 284, 457);
    const narrow = shownCamera();
    expect(narrow.translation[0]).toBeCloseTo(-2.4918, 4);
    expect(narrow.translation[1]).toBeCloseTo(-1.438642, 4);
    expect(narrow.translation[2]).toBeCloseTo(-1.017273, 4);
    expect(narrow.distance).toBeCloseTo(fittedDistance(284, 457), 4);
    expect(narrow.distance).toBeGreaterThan(fittedDistance(417, 457));
    expect(narrow.quaternion).toEqual(rotation);
    // A collapsed surface has no aspect ratio to fit; the last framing stays.
    resizeTo(surface, 0, 457);
    expect(shownCamera()).toEqual(narrow);
    resizeTo(surface, 284, 0);
    expect(shownCamera()).toEqual(narrow);
    viewer.dispose();
    resizeTo(surface, 417, 457);
    expect(shownCamera()).toEqual(narrow);
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
