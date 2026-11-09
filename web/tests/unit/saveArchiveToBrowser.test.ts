import { afterEach, describe, expect, it, vi } from "vitest";

import { saveArchiveToBrowser } from "../../src/index";

describe("saveArchiveToBrowser, exported by the library (#255)", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("downloads the archive's blob under its filename, then revokes the URL", () => {
    const blob = new Blob(["zip bytes"], { type: "application/zip" });
    const createObjectURL = vi.fn(() => "blob:archive");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL });
    const clicked: { href: string; download: string; inDocument: boolean }[] =
      [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      clicked.push({
        href: this.href,
        download: this.download,
        inDocument: document.body.contains(this),
      });
    });

    saveArchiveToBrowser({ blob, filename: "Si.cif.zip" });

    expect(createObjectURL).toHaveBeenCalledWith(blob);
    expect(clicked).toEqual([
      { href: "blob:archive", download: "Si.cif.zip", inDocument: true },
    ]);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:archive");
    expect(document.querySelector("a[download]")).toBeNull();
    vi.unstubAllGlobals();
  });
});
