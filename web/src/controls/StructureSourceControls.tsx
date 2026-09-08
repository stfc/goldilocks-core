import { type DragEvent, useRef, useState } from "react";
import {
  Button,
  FileButton,
  Loader,
  Paper,
  SimpleGrid,
  Stack,
  Text,
} from "@mantine/core";
import { Upload } from "lucide-react";

import type { StructureInspection, StructureSource } from "../api/coreClient";

export function StructureSourceControls({
  source,
  inspection,
  inspecting,
  onOpen,
}: {
  readonly source: StructureSource | null;
  readonly inspection: StructureInspection | null;
  readonly inspecting: boolean;
  readonly onOpen: (source: StructureSource) => Promise<void>;
}) {
  const resetFileInput = useRef<(() => void) | null>(null);
  const selectionEpoch = useRef(0);
  const [dragging, setDragging] = useState(false);
  const [readError, setReadError] = useState<string | null>(null);

  async function openFile(file: File): Promise<void> {
    const selection = ++selectionEpoch.current;
    setReadError(null);
    if (file.size > 5 * 1024 * 1024) {
      setReadError("Structure files must be 5 MB or smaller.");
      return;
    }
    if (file.size === 0) {
      setReadError("The selected structure file is empty.");
      return;
    }
    try {
      const content = await file.text();
      if (selection !== selectionEpoch.current) return;
      await onOpen({
        kind: "inline",
        name: file.name,
        format: structureFormat(file.name),
        content,
      });
    } catch {
      if (selection === selectionEpoch.current) {
        setReadError("The selected file could not be read.");
      }
    }
  }

  function fileSelected(file: File | null): void {
    resetFileInput.current?.();
    if (file !== null) void openFile(file);
  }

  function fileDropped(event: DragEvent<HTMLDivElement>): void {
    event.preventDefault();
    setDragging(false);
    const file = event.dataTransfer.files[0];
    if (file !== undefined) void openFile(file);
  }

  let sourceHelp = "CIF or POSCAR · 5 MB maximum file size";
  if (source !== null) sourceHelp = "Inspecting structure";
  if (inspection !== null) {
    sourceHelp = `${String(inspection.structure.site_count)} sites · parsed`;
  }

  return (
    <>
      <Paper
        withBorder
        p="md"
        bg={
          dragging
            ? "var(--mantine-primary-color-light)"
            : "var(--mantine-color-body)"
        }
        onDragEnter={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragOver={(event) => {
          event.preventDefault();
        }}
        onDragLeave={() => {
          setDragging(false);
        }}
        onDrop={fileDropped}
        aria-busy={inspecting}
      >
        <Stack align="center" gap="xs">
          {inspecting ? (
            <Loader size="sm" aria-hidden="true" />
          ) : (
            <Upload aria-hidden="true" size={18} />
          )}
          <Text fw={600} truncate w="100%" ta="center">
            {source?.name ?? "Drop a structure"}
          </Text>
          <Text id="structure-source-help" c="dimmed" size="sm" ta="center">
            {sourceHelp}
          </Text>
          <FileButton
            resetRef={resetFileInput}
            onChange={fileSelected}
            disabled={inspecting}
          >
            {(fileButtonProps) => (
              <Button
                {...fileButtonProps}
                variant="subtle"
                type="button"
                aria-describedby="structure-source-help"
                aria-label={
                  source === null
                    ? "Choose a CIF or POSCAR structure"
                    : "Replace structure file"
                }
                disabled={inspecting}
              >
                {source === null ? "Browse files" : "Replace file"}
              </Button>
            )}
          </FileButton>
        </Stack>
      </Paper>
      {readError === null ? null : (
        <Text c="red" size="sm" role="alert">
          {readError}
        </Text>
      )}
      {inspection === null ? null : (
        <StructureSummary inspection={inspection} />
      )}
    </>
  );
}

function StructureSummary({
  inspection,
}: {
  readonly inspection: StructureInspection;
}) {
  const structure = inspection.structure;
  const elements = [
    ...new Set(
      structure.sites.flatMap((site) =>
        site.species.map((species) => species.symbol),
      ),
    ),
  ];
  return (
    <SimpleGrid
      component="dl"
      cols={2}
      mt="md"
      mb={0}
      aria-label="Inspected structure summary"
    >
      <div>
        <Text component="dt" c="dimmed" size="sm">
          Formula
        </Text>
        <Text component="dd" m={0}>
          {structure.formula}
        </Text>
      </div>
      <div>
        <Text component="dt" c="dimmed" size="sm">
          Elements
        </Text>
        <Text component="dd" m={0}>
          {elements.join(" · ")}
        </Text>
      </div>
      <div>
        <Text component="dt" c="dimmed" size="sm">
          Cell volume
        </Text>
        <Text component="dd" m={0}>
          {structure.lattice.volume_angstrom3.toFixed(1)} Å³
        </Text>
      </div>
      <div>
        <Text component="dt" c="dimmed" size="sm">
          Periodicity
        </Text>
        <Text component="dd" m={0}>
          {structure.periodicity.every(Boolean) ? "3D" : "Partial"}
        </Text>
      </div>
    </SimpleGrid>
  );
}

function structureFormat(name: string): "cif" | "poscar" {
  return name.toLowerCase().endsWith(".cif") ? "cif" : "poscar";
}
