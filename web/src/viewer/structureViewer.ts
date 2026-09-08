import type { GLViewer } from "3dmol";

export interface StructureViewer {
  show(canonicalCif: string): void;
  refreshTheme(): void;
  dispose(): void;
}

export type StructureViewerFactory = (
  element: HTMLElement,
  signal: AbortSignal,
) => StructureViewer | Promise<StructureViewer>;

// 3dmol 2.5.5 has no viewer destructor: clear() only clears the scene, and
// setContainer() installs additional canvas listeners. Keep one viewer and its
// original container for the document lifetime; each viewport leases it.
let retained: { viewer: GLViewer; surface: HTMLDivElement } | undefined;
let owner: symbol | undefined;

export const attachStructureViewer: StructureViewerFactory = async (
  element,
  signal,
) => {
  signal.throwIfAborted();
  const { createViewer } = await import("3dmol");
  signal.throwIfAborted();
  if (retained === undefined) {
    const surface = document.createElement("div");
    surface.style.cssText = "position:relative;width:100%;height:100%";
    element.append(surface);
    try {
      retained = {
        viewer: createViewer(surface, { antialias: true }),
        surface,
      };
    } catch (error) {
      surface.remove();
      throw error;
    }
  }
  const { viewer, surface } = retained;
  const lease = Symbol();
  owner = lease;
  element.append(surface);
  // The library's ResizeObserver and IntersectionObserver stay attached to
  // this same surface, including while it is detached between inspections.
  viewer.resize();

  return {
    show(canonicalCif): void {
      if (owner !== lease) return;
      viewer.clear();
      const model = viewer.addModel(canonicalCif, "cif");
      viewer.setStyle(
        {},
        {
          sphere: { scale: 0.3, colorscheme: "Jmol" },
          stick: { radius: 0.12, colorscheme: "Jmol" },
        },
      );
      const rootStyle = getComputedStyle(document.documentElement);
      viewer.addUnitCell(model, {
        box: {
          color: rootStyle.getPropertyValue("--mantine-color-gray-6").trim(),
          linewidth: 1.5,
        },
      });
      viewer.zoomTo();
      viewer.render();
    },
    refreshTheme(): void {
      if (owner !== lease) return;
      const backgroundColor = getComputedStyle(document.documentElement)
        .getPropertyValue("--mantine-color-body")
        .trim();
      viewer.setBackgroundColor(backgroundColor, 1);
    },
    dispose(): void {
      if (owner !== lease) return;
      owner = undefined;
      viewer.clear();
      surface.remove();
    },
  };
};
