import type { GLViewer } from "3dmol";

export interface StructureViewer {
  show(canonicalCif: string): void;
  dispose(): void;
}

export type StructureViewerFactory = (
  element: HTMLElement,
) => StructureViewer | Promise<StructureViewer>;

export const attachStructureViewer: StructureViewerFactory = async (element) => {
  const probe = document.createElement("canvas");
  if (
    probe.getContext("webgl2") === null &&
    probe.getContext("webgl") === null
  ) {
    throw new Error("WebGL is unavailable");
  }
  const { createViewer } = await import("3dmol");
  const viewer: GLViewer = createViewer(element, {
    antialias: true,
    backgroundColor: "#111a1f",
  });
  const observer = new ResizeObserver(() => {
    viewer.resize();
    viewer.render();
  });
  observer.observe(element);

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
        box: { color: "#d7aa4a", linewidth: 1.5 },
      });
      viewer.zoomTo();
      viewer.render();
    },
    dispose(): void {
      observer.disconnect();
      viewer.clear();
      element.replaceChildren();
    },
  };
};
