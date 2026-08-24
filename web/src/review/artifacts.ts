import type { ComputationResult } from "../api/coreClient";

type InputArtifact = NonNullable<
  ComputationResult["records"]["dft_input_data"]
>["artifacts"][number];

export function artifactDigest(
  artifacts: readonly InputArtifact[],
  filename: string | null,
): string | null {
  if (filename === null) return null;
  return (
    artifacts.find(
      (artifact) =>
        artifact.path === filename || artifact.path.endsWith(`/${filename}`),
    )?.sha256 ?? null
  );
}
