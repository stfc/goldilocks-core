import type { ComputationResult } from "../api/coreClient";

type InputManifest = NonNullable<
  ComputationResult["records"]["dft_input_data"]
>["manifest"];

export function artifactMetadata(
  manifest: InputManifest | undefined,
  filename: string | null,
): { sha256: string | undefined; size_bytes: number | undefined } | undefined {
  const files = manifest?.files;
  if (
    filename === null ||
    typeof files !== "object" ||
    files === null ||
    Array.isArray(files)
  ) {
    return undefined;
  }
  const descriptor: unknown = Object.entries(files).find(
    ([path]) => path === filename || path.endsWith(`/${filename}`),
  )?.[1];
  if (typeof descriptor !== "object" || descriptor === null) {
    return undefined;
  }
  return {
    sha256:
      "sha256" in descriptor && typeof descriptor.sha256 === "string"
        ? descriptor.sha256
        : undefined,
    size_bytes:
      "size_bytes" in descriptor &&
      typeof descriptor.size_bytes === "number" &&
      Number.isFinite(descriptor.size_bytes) &&
      descriptor.size_bytes >= 0
        ? descriptor.size_bytes
        : undefined,
  };
}
