import { useEffect, useState } from "react";
import { Accordion, Code, Group, Table, Text, Title } from "@mantine/core";

import type { ArchiveDownload } from "../api/coreClient";
import {
  type ArchiveContents,
  type ArchiveFile,
  type InputManifest,
  artifactMetadata,
  unzipArchive,
} from "./artifacts";
import { GeneratedInputPreview } from "./GeneratedInputPreview";
import { readableName } from "./readableName";

/** Mirrors the roles `bundle.py`/`_bundle.py` actually assign in
 * `goldilocks.json` (verified against source, not guessed) -- this is
 * the display order the user asked for: rendered code input, in the order
 * its steps run (the manifest's `steps`, #222), then the submission
 * script, then pseudopotentials and their table's licence, then the
 * machine-readable manifest, then the human-readable docs. */
const ROLE_RANK: Readonly<Record<string, number>> = {
  input: 0,
  submission_script: 1,
  pseudopotential: 2,
  licence: 3,
  manifest: 4,
  readme: 5,
  citations: 5,
};
const UNRANKED = 6;

function roleOf(
  manifest: InputManifest | null,
  path: string,
): string | undefined {
  const listed = manifest?.files[path]?.role;
  // The manifest can't list its own role -- doing so would change its
  // own bytes, and therefore its own sha256, after the fact -- so
  // `goldilocks.json` is the one file this codebase already special-cases
  // by name elsewhere (artifacts.ts's `unzipArchive`).
  if (listed === undefined && path === "goldilocks.json") return "manifest";
  return listed;
}

function orderedFiles(
  files: readonly ArchiveFile[],
  manifest: InputManifest | null,
): ArchiveFile[] {
  const runOrder = new Map(
    (manifest === null ? [] : manifest.steps)
      .flatMap((step) => step.files)
      .map((path, index) => [path, index]),
  );
  const placeOf = (path: string) => runOrder.get(path) ?? runOrder.size;
  return [...files].sort((a, b) => {
    const rankA = ROLE_RANK[roleOf(manifest, a.path) ?? ""] ?? UNRANKED;
    const rankB = ROLE_RANK[roleOf(manifest, b.path) ?? ""] ?? UNRANKED;
    if (rankA !== rankB) return rankA - rankB;
    const placeA = placeOf(a.path);
    const placeB = placeOf(b.path);
    return placeA !== placeB ? placeA - placeB : a.path.localeCompare(b.path);
  });
}

/** The files of `archive`, or `placeholder` (why there are none yet) while
 * it is null. */
export function GeneratedInputReview({
  archive,
  placeholder,
}: {
  readonly archive: ArchiveDownload | null;
  readonly placeholder: string;
}) {
  const contents = useUnzippedArchive(archive);

  if (archive === null) {
    return (
      <div>
        <Title order={3}>Generated inputs</Title>
        <Text c="dimmed">{placeholder}</Text>
      </div>
    );
  }
  if (contents === null) {
    return (
      <div>
        <Title order={3}>Generated inputs</Title>
        <Text c="dimmed">Reading the generated archive…</Text>
      </div>
    );
  }

  const { manifest, files } = contents;
  if (files.length === 0) {
    return (
      <div>
        <Title order={3}>Generated inputs</Title>
        <Text c="dimmed">No generated input files.</Text>
      </div>
    );
  }

  return (
    <div>
      <Group component="header" justify="space-between" mb="xs">
        <Title order={3}>Generated inputs</Title>
        <Text size="sm" c="dimmed">
          {files.length} files
        </Text>
      </Group>
      <Accordion multiple transitionDuration={0}>
        {orderedFiles(files, manifest).map((file) => {
          const role = roleOf(manifest, file.path);
          const metadata = artifactMetadata(manifest, file.path);
          return (
            <Accordion.Item key={file.path} value={file.path}>
              <Accordion.Control>
                <Group justify="space-between" wrap="nowrap" gap="xs">
                  <Text size="sm" fw={600} style={{ overflowWrap: "anywhere" }}>
                    {file.path}
                  </Text>
                  {metadata?.sha256 === undefined ? null : (
                    <Code>{metadata.sha256.slice(0, 10)}</Code>
                  )}
                </Group>
              </Accordion.Control>
              <Accordion.Panel>
                {role === "pseudopotential" ? (
                  <PseudopotentialEntry
                    content={file.content}
                    sizeBytes={metadata?.size_bytes}
                    sha256={metadata?.sha256}
                  />
                ) : (
                  <GeneratedInputPreview
                    path={file.path}
                    content={file.content}
                  />
                )}
              </Accordion.Panel>
            </Accordion.Item>
          );
        })}
      </Accordion>
    </div>
  );
}

/** A pseudopotential file's bytes aren't meant to be read by a human --
 * show the handful of identifying header fields instead (parsed from
 * the UPF v2 `<PP_HEADER .../>` tag when present) rather than dumping
 * the raw file. */
function PseudopotentialEntry({
  content,
  sizeBytes,
  sha256,
}: {
  readonly content: string;
  readonly sizeBytes: number | undefined;
  readonly sha256: string | undefined;
}) {
  const header = parsePseudoHeader(content);
  return (
    <Table>
      <Table.Tbody>
        {header === null
          ? null
          : Object.entries(header).map(([key, value]) => (
              <Table.Tr key={key}>
                <Table.Th scope="row">{readableName(key)}</Table.Th>
                <Table.Td style={{ overflowWrap: "anywhere" }}>
                  {value}
                </Table.Td>
              </Table.Tr>
            ))}
        <Table.Tr>
          <Table.Th scope="row">Size</Table.Th>
          <Table.Td>
            {sizeBytes === undefined
              ? "Unknown"
              : `${(sizeBytes / 1024).toFixed(1)} KB`}
          </Table.Td>
        </Table.Tr>
        <Table.Tr>
          <Table.Th scope="row">SHA-256</Table.Th>
          <Table.Td style={{ overflowWrap: "anywhere" }}>
            <Code>{sha256 ?? "unlisted"}</Code>
          </Table.Td>
        </Table.Tr>
      </Table.Tbody>
    </Table>
  );
}

function parsePseudoHeader(content: string): Record<string, string> | null {
  const tag = /<PP_HEADER\b([^>]*)\/?>/i.exec(content);
  const tagBody = tag?.[1];
  if (tagBody === undefined) return null;
  const attributes: Record<string, string> = {};
  const attributePattern = /([\w.]+)\s*=\s*"([^"]*)"/g;
  for (const match of tagBody.matchAll(attributePattern)) {
    const [, key, value] = match;
    if (key === undefined || value === undefined) continue;
    attributes[key] = value.trim();
  }
  return Object.keys(attributes).length === 0 ? null : attributes;
}

/** Unzipping is genuinely async work driven by an external blob, not
 * derivable during render -- a legitimate effect, unlike CalculationForm's
 * JsonOverrideControl (which only needed to resync local text state). */
function useUnzippedArchive(
  archive: ArchiveDownload | null,
): ArchiveContents | null {
  const [state, setState] = useState<{
    readonly archive: ArchiveDownload;
    readonly contents: ArchiveContents;
  } | null>(null);

  useEffect(() => {
    if (archive === null) return;
    let cancelled = false;
    void unzipArchive(archive).then((contents) => {
      if (!cancelled) setState({ archive, contents });
    });
    return () => {
      cancelled = true;
    };
  }, [archive]);

  return state?.archive === archive ? state.contents : null;
}
