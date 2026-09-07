import { Table, Text } from "@mantine/core";
import type { ReactNode } from "react";

import type { ComputationResult } from "../api/coreClient";

type Records = ComputationResult["records"];
type Provenance = NonNullable<Records["k_points"]>["provenance"];
type Smearing = NonNullable<Records["advice"]>["smearing"];
type Fact = readonly [label: string, value: ReactNode, provenance?: Provenance];
type RecordPresenters = Record<
  keyof Records,
  (records: Records) => readonly Fact[]
>;

const SOURCE_NAMES: Record<Provenance["source"], string> = {
  analysis: "Structure analysis",
  user_hint: "Your override",
  default: "Default",
  model: "Model prediction",
  lookup: "Reference lookup",
  fallback: "Fallback",
};
const DIMENSION_NAMES = {
  "3d": "3D bulk",
  "2d": "2D",
  "1d": "1D",
  molecule: "Molecule",
  unknown: "Unknown",
};
const ELECTRONIC_NAMES = {
  metal: "Metal",
  insulator: "Insulator",
  likely_metal: "Likely metal",
  unknown: "Unknown",
};
const SMEARING_NAMES: Record<string, string> = {
  cold: "Cold smearing",
  gaussian: "Gaussian smearing",
  mp: "Methfessel–Paxton smearing",
};
const RELATIVITY_NAMES: Record<string, string> = {
  scalar: "Scalar relativistic",
  full: "Fully relativistic",
  "non-relativistic": "Non-relativistic",
};

export function ScientificRecord({
  name,
  result,
}: {
  readonly name: keyof Records;
  readonly result: ComputationResult;
}) {
  const facts = recordPresenters[name](result.records);
  if (facts.length === 0) return null;
  return (
    <Table
      layout="fixed"
      verticalSpacing="sm"
      style={{ overflowWrap: "anywhere" }}
    >
      <Table.Tbody>
        {facts.map(([label, content, provenance], index) => (
          <Table.Tr key={`${label}-${String(index)}`}>
            <Table.Th scope="row">{label}</Table.Th>
            <Table.Td>
              {provenance === undefined ? (
                (content ?? "None reported")
              ) : (
                <Decision provenance={provenance}>{content}</Decision>
              )}
            </Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}

const recordPresenters: RecordPresenters = {
  analysis: ({ analysis: value }) => {
    if (value === undefined) return [];
    return [
      [
        "Composition",
        `${value.reduced_formula} · ${String(value.site_count)} atomic sites`,
      ],
      ["Elements", value.elements.join(", ")],
      ["Dimensionality", DIMENSION_NAMES[value.dimensionality]],
      ["Crystal system", value.crystal_system ?? "Not determined"],
      [
        "Space group",
        [value.space_group_symbol, value.space_group_number]
          .filter((item) => item !== null)
          .join(" · ") || "Not determined",
      ],
      ["Electronic character", ELECTRONIC_NAMES[value.electronic_character]],
      ["Classification source", value.electronic_character_source],
      ...(value.electronic_character_confidence === null
        ? []
        : [
            [
              "Classification confidence",
              `${(value.electronic_character_confidence * 100).toFixed(1)}%`,
            ] as const,
          ]),
      [
        "Magnetic candidates",
        value.magnetic_elements.join(", ") || "None identified",
      ],
      ["Heavy elements", value.heavy_elements.join(", ") || "None identified"],
      ["Disordered sites", value.disordered_site_count],
      [
        "Warnings",
        <WarningText
          warnings={[...value.analysis_warnings, ...value.disorder_warnings]}
        />,
      ],
    ];
  },
  advice: ({ advice: value }) => {
    if (value === undefined) return [];
    let spinOrbit = "Not enabled";
    if (value.spin_orbit.consider)
      spinOrbit = "Not enabled · consider for this system";
    if (value.spin_orbit.enabled) spinOrbit = "Enabled";
    return [
      [
        "Spin treatment",
        value.magnetism.spin_polarized
          ? "Spin polarized"
          : "Non-spin-polarized",
        value.magnetism.provenance,
      ],
      ["Spin–orbit coupling", spinOrbit, value.spin_orbit.provenance],
      ["Occupations", occupations(value.smearing), value.smearing.provenance],
      [
        "Dispersion",
        value.vdw.use_vdw
          ? (value.vdw.method?.toUpperCase() ?? "Enabled")
          : "Disabled",
        value.vdw.provenance,
      ],
      [
        "SCF convergence",
        <>
          {value.convergence.conv_thr} Ry threshold; up to{" "}
          {value.convergence.electron_maxstep} steps; mixing β ={" "}
          {value.convergence.mixing_beta}
        </>,
        value.convergence.provenance,
      ],
      [
        "Pseudopotential requirements",
        <>
          {value.pseudopotential_requirements.functional} ·{" "}
          {value.pseudopotential_requirements.accuracy} ·{" "}
          {relativity(value.pseudopotential_requirements.relativistic)}
          {value.pseudopotential_requirements.pseudo_type
            ? ` · ${value.pseudopotential_requirements.pseudo_type}`
            : ""}
        </>,
        value.pseudopotential_requirements.provenance,
      ],
    ];
  },
  k_points: ({ k_points: value }) => {
    if (value === undefined) return [];
    return [
      ["Grid", value.grid.join(" × ")],
      ["Mesh", value.mesh_type],
      ["QE shift flags", value.shift.join(" ")],
      [
        "Sampling offset",
        value.shift.every((flag) => flag === 0)
          ? "Unshifted · includes Γ"
          : "Half-grid shift on flagged axes",
      ],
      ["Basis", undefined, value.provenance],
    ];
  },
  selection: ({ selection: value }) => {
    if (value === undefined) return [];
    return [
      ...value.pseudopotentials.map(
        (item) =>
          [
            item.element,
            <>
              <Decision provenance={item.provenance}>
                {item.filename ?? "Filename unavailable"}
                <br />
                {item.functional ?? "Functional not specified"} ·{" "}
                {relativity(item.relativistic)}
                <br />
                Wavefunction: {quantity(item.ecutwfc_ry, "Ry")}
                <br />
                Charge density: {quantity(item.ecutrho_ry, "Ry")}
              </Decision>
              <WarningText warnings={item.warnings} />
            </>,
          ] as const,
      ),
      ["Warnings", <WarningText warnings={value.warnings} />],
    ];
  },
  generated_files: ({ generated_files: files }) => {
    if (files === undefined) return [];
    return files.map(
      (file) =>
        [
          file.path,
          `${file.role} · available in Generated inputs and the download`,
        ] as const,
    );
  },
  dft_input_data: ({ dft_input_data: value }) => {
    if (value === undefined) return [];
    return [
      ["Core version", value.runtime.core_version],
      [
        "Pseudopotential set",
        `${value.pseudopotential_set.provider} · ${value.pseudopotential_set.version ?? "unversioned"}`,
      ],
      ["Licence", value.pseudopotential_set.licence],
      [
        "Citations",
        <ul>
          {value.citations.map((citation) => (
            <li key={citation}>{citation}</li>
          ))}
        </ul>,
      ],
      ...value.runtime.models.map(
        (model) => [model.name, `${model.version} · ${model.target}`] as const,
      ),
      [
        "Archive contents",
        <ul>
          {value.artifacts.map((artifact) => (
            <li key={artifact.path}>
              {artifact.path} · {artifact.size_bytes.toLocaleString()} bytes
            </li>
          ))}
        </ul>,
      ],
    ];
  },
};

function Decision({
  provenance,
  children,
}: {
  readonly provenance: Provenance;
  readonly children?: ReactNode;
}) {
  return (
    <>
      {children === undefined ? null : <Text size="sm">{children}</Text>}
      <Text size="sm">{provenance.reason}</Text>
      <Text size="sm" c="dimmed">
        {SOURCE_NAMES[provenance.source]}
        {provenance.data_source === null ? "" : ` · ${provenance.data_source}`}
        {provenance.confidence === null
          ? ""
          : ` · ${(provenance.confidence * 100).toFixed(1)}% confidence`}
      </Text>
      <WarningText warnings={provenance.warnings} />
    </>
  );
}

function WarningText({ warnings }: { readonly warnings: readonly string[] }) {
  return warnings.length === 0 ? null : (
    <ul>
      {warnings.map((warning) => (
        <li key={warning}>{warning}</li>
      ))}
    </ul>
  );
}

function occupations(smearing: Smearing): string {
  const type = smearing.smearing_type;
  if (type === null) return "Not specified";
  if (type === "fixed") return "Fixed occupations";
  return `${SMEARING_NAMES[type] ?? type}${smearing.width_ry === null ? "" : ` · ${String(smearing.width_ry)} Ry`}`;
}

function quantity(value: number | null, unit: string): string {
  return value === null ? "Not provided" : `${String(value)} ${unit}`;
}

function relativity(value: string | null): string {
  return (
    RELATIVITY_NAMES[value ?? ""] ??
    value ??
    "Relativistic treatment not specified"
  );
}
