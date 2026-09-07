import type { GLViewer } from "3dmol";

export interface StructureViewer {
  show(canonicalCif: string): void;
  dispose(): void;
}

export type StructureViewerFactory = (
  element: HTMLElement,
) => StructureViewer | Promise<StructureViewer>;

export const attachStructureViewer: StructureViewerFactory = async (
  element,
) => {
  const probe = document.createElement("canvas");
  if (
    probe.getContext("webgl2") === null &&
    probe.getContext("webgl") === null
  ) {
    throw new Error("WebGL is unavailable");
  }
  const { createViewer } = await import("3dmol");
  const surface = document.createElement("div");
  surface.style.cssText = "position:relative;width:100%;height:100%";
  element.append(surface);
  const rootStyle = getComputedStyle(document.documentElement);
  const backgroundColor = rootStyle
    .getPropertyValue("--mantine-color-body")
    .trim();
  const unitCellColor = rootStyle
    .getPropertyValue("--mantine-color-gray-6")
    .trim();
  let viewer: GLViewer;
  try {
    viewer = createViewer(surface, {
      antialias: true,
      backgroundColor,
    });
  } catch (error) {
    surface.remove();
    throw error;
  }
  const observer = new ResizeObserver(() => {
    viewer.resize();
    viewer.render();
  });
  observer.observe(surface);

  return {
    show(canonicalCif): void {
      viewer.clear();
      const model = viewer.addModel(canonicalCif, "cif");
      viewer.setStyle(
        {},
        {
          sphere: { scale: 0.3, colorscheme: "Jmol" },
          stick: { radius: 0.12, colorscheme: "Jmol" },
        },
      );
      viewer.addUnitCell(model, {
        box: { color: unitCellColor, linewidth: 1.5 },
      });
      viewer.zoomTo();
      viewer.render();
    },
    dispose(): void {
      observer.disconnect();
      viewer.clear();
      surface.remove();
    },
  };
};
