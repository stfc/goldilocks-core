import { type DragEvent, useRef, useState } from "react";
import {
  Button,
  FileButton,
  Group,
  Loader,
  Paper,
  Stack,
  Text,
} from "@mantine/core";
import { Upload } from "lucide-react";

import type { StructureInput, StructureInspection } from "../api/coreClient";
import { formatSiteCount } from "../viewer/siteCount";

export function StructureSourceControls({
  source,
  inspection,
  inspecting,
  onOpen,
}: {
  readonly source: StructureInput | null;
  readonly inspection: StructureInspection | null;
  readonly inspecting: boolean;
  readonly onOpen: (input: StructureInput) => Promise<void>;
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
        structure_content: content,
        structure_name: file.name,
        structure_format: structureFormat(file.name),
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
    sourceHelp = `${formatSiteCount(inspection.structure.site_count, "site")} · parsed`;
  }

  const dropzoneProps = {
    onDragEnter: (event: DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      setDragging(true);
    },
    onDragOver: (event: DragEvent<HTMLDivElement>) => {
      event.preventDefault();
    },
    onDragLeave: () => {
      setDragging(false);
    },
    onDrop: fileDropped,
    "aria-busy": inspecting,
    bg: dragging
      ? "var(--mantine-primary-color-light)"
      : "var(--mantine-color-body)",
  };

  const fileButton = (
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
  );

  return (
    <>
      {/* Once a structure is loaded the viewer needs most of this card's
       * height, so the dropzone collapses from the spacious first-run
       * empty state into a single compact status row (same drop target,
       * same controls) instead of staying full-size forever. */}
      {source === null ? (
        <Paper withBorder p="md" {...dropzoneProps}>
          <Stack align="center" gap="xs">
            <Upload aria-hidden="true" size={18} />
            <Text fw={600} truncate w="100%" ta="center">
              Drop a structure
            </Text>
            <Text id="structure-source-help" c="dimmed" size="sm" ta="center">
              {sourceHelp}
            </Text>
            {fileButton}
          </Stack>
        </Paper>
      ) : (
        <Paper withBorder p="xs" {...dropzoneProps}>
          <Stack gap={4}>
            {/* The filename gets its own full-width row -- sharing a row
             * with the site-count/status text left too little room for
             * either, so both truncated into near-unreadable fragments. */}
            <Group gap="xs" wrap="nowrap" style={{ minWidth: 0 }}>
              {inspecting ? (
                <Loader size="xs" aria-hidden="true" />
              ) : (
                <Upload aria-hidden="true" size={16} />
              )}
              <Text fw={600} truncate>
                {source.structure_name}
              </Text>
            </Group>
            <Group justify="space-between" wrap="nowrap" gap="xs">
              <Text id="structure-source-help" c="dimmed" size="sm" truncate>
                {sourceHelp}
              </Text>
              {fileButton}
            </Group>
            {inspection === null ? null : (
              <StructureSummary inspection={inspection} />
            )}
          </Stack>
        </Paper>
      )}
      {readError === null ? null : (
        <Text c="red" size="sm" role="alert">
          {readError}
        </Text>
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
  // No periodicity token: pymatgen marks every CIF/POSCAR fully periodic,
  // so it never varies, and next to the formula it reads as the
  // structure's dimensionality (a monolayer would show "3D").
  return (
    <Text
      size="sm"
      c="dimmed"
      truncate
      aria-label="Inspected structure summary"
    >
      {structure.formula} · {elements.join(" ")} ·{" "}
      {structure.lattice.volume_angstrom3.toFixed(1)} Å³
    </Text>
  );
}

function structureFormat(name: string): "cif" | "poscar" {
  return name.toLowerCase().endsWith(".cif") ? "cif" : "poscar";
}
